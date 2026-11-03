"""Measurement harness: cluster bootstrap of the baseline (M0) and main (M1) models.

    python -m src.collector --config config.yaml            # mode from config.yaml
    python -m src.collector --config config.yaml --mode full

One "measurement" is one bootstrap replicate: the states are resampled with replacement
(whole states, because observations of one state over the years are correlated), the
panel is rebuilt from the drawn states, and M0 and M1 are re-estimated on it.

Design rules (Week 7 checklist):
* Warm-up:   the first ``n_warmup`` replicates are logged with phase="warmup" and excluded
             from all metrics. They absorb cold-start costs (lazy imports, memory
             allocation, CPU caches) that inflate the runtime of the first fits.
* JSONL:     one JSON object per line in data/raw/test_run.jsonl. Each line is flushed
             right away, so a crash never corrupts the replicates already written.
* I/O isolation: the stopwatch (time.perf_counter_ns) wraps only the model fit; building
             the record and writing it to disk happen after the stopwatch has stopped.
* Errors:    a failed or degenerate fit is NOT dropped. It is logged with status
             "skipped", "rank_deficient" or "error" and counted in the error rate
             (guardrail metric), which avoids selection bias.
* Metadata:  hardware, software, seed and SHA-256 of the inputs go to test_run_meta.json.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
import statsmodels

from . import __version__
from .analysis import Y, fit_model
from .config import load_config, resolve, sha256_file
from .load_data import build_panel

# ----------------------------------------------------------------------------- helpers


def _now_iso() -> str:
    """UTC timestamp with microseconds, e.g. 2026-10-22T05:15:03.123456+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _clean(value):
    """Make a value JSON-safe: numpy scalars -> Python, NaN -> null."""
    if isinstance(value, (np.floating, float)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def _ram_gb() -> float | None:
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 2)
    except (ValueError, OSError, AttributeError):  # not available on Windows
        return None


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def environment_metadata(cfg: dict, bench: dict) -> dict:
    """Everything needed to reproduce the run on another machine."""
    mode = cfg["data"]["mode"]
    inputs = {}
    for key, rel in cfg["data"][mode].items():
        if not isinstance(rel, str):
            continue
        path = resolve(cfg, rel)
        if path.is_file():
            inputs[key] = {"path": rel, "sha256": sha256_file(path)}
        elif path.is_dir():
            inputs[key] = {"path": rel, "files": {p.name: sha256_file(p) for p in sorted(path.glob("*.csv"))}}
    return {
        "pipeline_version": __version__,
        "started_at": _now_iso(),
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "packages": {"numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                     "statsmodels": statsmodels.__version__},
        "config": {"path": Path(cfg["_config_path"]).name, "sha256": sha256_file(cfg["_config_path"])},
        "data_mode": mode,
        "inputs": inputs,
        "random_seed": int(cfg["project"]["random_seed"]),
        "n_warmup": bench["n_warmup"],
        "n_runs": bench["n_runs"],
        "models": bench["models"],
    }


# ----------------------------------------------------------------------------- core


def model_specs(cfg: dict) -> dict:
    """Same specifications as M0 and M1 in analysis.run_models."""
    covs = list(cfg["model"]["covariates"])
    return {
        "M0": {"covariates": [], "year_fx": False},
        "M1": {"covariates": covs, "year_fx": bool(cfg["model"]["year_effects"])},
    }


def resample_states(panel: pd.DataFrame, rng: np.random.Generator) -> tuple[pd.DataFrame, int]:
    """Cluster bootstrap draw. A state drawn twice becomes two separate clusters."""
    states = panel["state"].unique()
    drawn = rng.choice(states, size=len(states), replace=True)
    parts = [panel[panel["state"] == s].assign(state=f"{s}#{k}") for k, s in enumerate(drawn)]
    return pd.concat(parts, ignore_index=True), int(len(set(drawn)))


def measure(panel_b: pd.DataFrame, name: str, spec: dict, cfg: dict) -> tuple[dict, float]:
    """Fit one model and return (result fields, runtime in ms). Only the fit is timed."""
    t0 = time.perf_counter_ns()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = fit_model(panel_b, name, "", "robot", spec["covariates"], cfg,
                            year_fx=spec["year_fx"], sample=panel_b)
        runtime_ms = (time.perf_counter_ns() - t0) / 1e6
    except Exception as exc:  # noqa: BLE001 - every failure must be logged, not raised
        runtime_ms = (time.perf_counter_ns() - t0) / 1e6
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}, runtime_ms

    row = fit.row
    out = {k: row[k] for k in ("n_obs", "n_states", "coef", "std_err", "p_value", "adj_r2")}
    if row["status"] != "ok":
        out.update(status="skipped", error=row["status"])
    elif np.linalg.matrix_rank(fit.exog.values) < fit.exog.shape[1]:
        # OLS still returns numbers here, but beta is not identified: flag instead of trusting it.
        out.update(status="rank_deficient", error="design matrix is not full rank")
    elif not np.isfinite(row["coef"]):
        out.update(status="error", error="non-finite coefficient")
    else:
        out.update(status="ok", error=None)
    return out, runtime_ms


def summarize(records: list[dict]) -> pd.DataFrame:
    """Inline summary of the benchmark phase (warm-up excluded)."""
    df = pd.DataFrame(records)
    df = df[df["phase"] == "benchmark"]
    rows = []
    for model, g in df.groupby("model", sort=True):
        ok = g[g["status"] == "ok"]
        coef, rt = ok["coef_robot"], g["runtime_ms"]
        rows.append({
            "model": model,
            "n_runs": len(g),
            "error_rate": round(1 - len(ok) / len(g), 4) if len(g) else np.nan,
            "coef_mean": coef.mean(),
            "coef_sd": coef.std(ddof=1),
            "coef_median": coef.median(),
            "coef_ci95_low": coef.quantile(0.025),   # percentile bootstrap CI
            "coef_ci95_high": coef.quantile(0.975),
            "runtime_ms_p50": rt.quantile(0.50),
            "runtime_ms_p95": rt.quantile(0.95),
            "runtime_ms_p99": rt.quantile(0.99),
        })
    return pd.DataFrame(rows)


def run(cfg: dict, out_path: Path, meta_path: Path) -> pd.DataFrame:
    bench = cfg["benchmark"]
    n_warmup, n_runs = int(bench["n_warmup"]), int(bench["n_runs"])
    specs = model_specs(cfg)
    unknown = set(bench["models"]) - set(specs)
    if unknown:
        raise ValueError(f"benchmark.models: unknown models {sorted(unknown)}")

    # Data preparation is outside the measured loop.
    panel, _ = build_panel(cfg)
    covs = specs["M1"]["covariates"]
    panel = panel.dropna(subset=[Y, "robot"] + covs).reset_index(drop=True)  # same sample as M0/M1
    if panel["state"].nunique() < 2:
        raise ValueError("Need at least 2 states for a cluster bootstrap.")

    rng = np.random.default_rng(int(cfg["project"]["random_seed"]))
    meta = environment_metadata(cfg, bench)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    with open(out_path, "w", encoding="utf-8") as f:
        for run_id in range(n_warmup + n_runs):
            phase = "warmup" if run_id < n_warmup else "benchmark"
            panel_b, distinct = resample_states(panel, rng)
            for model in bench["models"]:
                result, runtime_ms = measure(panel_b, model, specs[model], cfg)  # timed part
                record = {                                                         # untimed part
                    "run_id": run_id,
                    "phase": phase,
                    "model": model,
                    "distinct_states": distinct,
                    "n_obs": result.get("n_obs"),
                    "coef_robot": result.get("coef"),
                    "std_err": result.get("std_err"),
                    "p_value": result.get("p_value"),
                    "adj_r2": result.get("adj_r2"),
                    "status": result["status"],
                    "error": result["error"],
                    "runtime_ms": round(runtime_ms, 4),
                    "timestamp": _now_iso(),
                }
                record = {k: _clean(v) for k, v in record.items()}
                f.write(json.dumps(record) + "\n")
                f.flush()
                records.append(record)

    meta["finished_at"] = _now_iso()
    meta["n_records"] = len(records)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return summarize(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cluster-bootstrap measurement harness (JSONL output)")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--mode", choices=["sample", "full"], help="override data.mode")
    parser.add_argument("--n-runs", type=int, help="override benchmark.n_runs")
    parser.add_argument("--n-warmup", type=int, help="override benchmark.n_warmup")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.mode:
        cfg["data"]["mode"] = args.mode
    if args.n_runs is not None:
        cfg["benchmark"]["n_runs"] = args.n_runs
    if args.n_warmup is not None:
        cfg["benchmark"]["n_warmup"] = args.n_warmup
    out_path = resolve(cfg, cfg["benchmark"]["output"])
    meta_path = resolve(cfg, cfg["benchmark"]["metadata"])

    started = time.perf_counter()
    summary = run(cfg, out_path, meta_path)
    limit = cfg["guardrails"].get("max_bootstrap_error_rate", 0.05)

    pd.set_option("display.width", 160)
    print(f"mode={cfg['data']['mode']} | records -> {out_path} | metadata -> {meta_path}")
    print(summary.round(6).to_string(index=False))
    for _, r in summary.iterrows():
        status = "PASS" if r["error_rate"] <= limit else "FLAG"
        print(f"guardrail | {r['model']} bootstrap error rate = {r['error_rate']:.2%} (<= {limit:.0%}) | {status}")
    if cfg["data"]["mode"] == "sample":
        print("NOTE: sample mode uses synthetic wages and 5 states; the numbers are a smoke test only.")
    print(f"total runtime {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
