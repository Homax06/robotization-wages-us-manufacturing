"""Cleaning and statistical aggregation of the bootstrap log (Week 8, steps 1-2).

    python -m src.process_data

Input
-----
* data/raw/test_run.jsonl   one line per bootstrap replicate and model (src/collector.py)
* data/processed/panel.csv  state x year panel used by the regressions (for descriptive statistics)

Output
------
* data/processed/metrics_summary.csv     aggregated metrics per model (main table for the README)
* data/processed/benchmark_clean.csv     benchmark-phase records with outlier flags
* data/processed/descriptive_stats.csv   Mean, SD, Median, p25, p75 of the study variables

Steps
-----
1. Load the JSONL log and validate its schema.
2. Drop the warm-up phase (cold-start replicates).
3. Count failed replicates per model as a guardrail metric. They are NOT silently dropped
   before counting, which would bias the result (selection bias).
4. Flag outliers with the 1.5 x IQR rule. Flags only: no record is deleted.
5. Aggregate: Mean, SD, Median, p25, p75, p95, p99 and a 95% confidence interval.
   * coef_robot: the replicates already ARE a bootstrap distribution, so the 95% CI is the
     2.5th-97.5th percentile of that distribution (percentile bootstrap).
   * runtime_ms: 95% CI of the median obtained by bootstrapping the runtimes (seed fixed).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config, resolve

REQUIRED_COLUMNS = {"run_id", "phase", "model", "status", "coef_robot", "runtime_ms"}
METRICS = {
    "coef_robot": "Coefficient on robot exposure (beta_1, log points per pp)",
    "runtime_ms": "Model fit runtime (ms)",
}


# ----------------------------------------------------------------------------- step 1


def load_log(path: str | Path) -> pd.DataFrame:
    """Read the JSONL log and check that every required field is present."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Bootstrap log not found: {path}. Run `python -m src.collector` first.")
    df = pd.read_json(path, lines=True)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise KeyError(f"{path.name}: missing fields {sorted(missing)}")
    if not set(df["phase"]) <= {"warmup", "benchmark"}:
        raise ValueError(f"Unexpected phase values: {sorted(set(df['phase']))}")
    return df


# ----------------------------------------------------------------------------- step 2


def drop_warmup(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only phase == 'benchmark'."""
    return df[df["phase"] == "benchmark"].reset_index(drop=True)


# ----------------------------------------------------------------------------- step 3


def error_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Share of replicates per model whose fit did not succeed (status != 'ok')."""
    g = df.groupby("model")["status"]
    out = pd.DataFrame({"n_runs": g.size(), "n_failed": g.apply(lambda s: int((s != "ok").sum()))})
    out["error_rate"] = out["n_failed"] / out["n_runs"]
    return out.reset_index()


# ----------------------------------------------------------------------------- step 4


def iqr_bounds(values: pd.Series, k: float = 1.5) -> tuple[float, float]:
    q1, q3 = values.quantile(0.25), values.quantile(0.75)
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def flag_outliers(df: pd.DataFrame, columns=tuple(METRICS), k: float = 1.5) -> pd.DataFrame:
    """Add boolean columns '<col>_outlier', computed separately for each model.

    Records are kept: an outlier in the coefficient is a legitimate bootstrap draw, an outlier
    in runtime is most likely background noise of the machine (garbage collection, other
    programs). Flagging lets us report both without deleting real data.
    """
    out = df.copy()
    for col in columns:
        flag = pd.Series(False, index=out.index)
        for _, idx in out.groupby("model").groups.items():
            values = out.loc[idx, col].dropna()
            if values.empty:
                continue
            low, high = iqr_bounds(values, k)
            flag.loc[values.index] = (values < low) | (values > high)
        out[f"{col}_outlier"] = flag
    return out


# ----------------------------------------------------------------------------- step 5


def bootstrap_ci(values: np.ndarray, stat=np.median, n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 42) -> tuple[float, float]:
    """Percentile bootstrap confidence interval of a statistic (median by default)."""
    values = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(n_boot, len(values)), replace=True)
    stats = np.apply_along_axis(stat, 1, draws)
    return float(np.quantile(stats, alpha / 2)), float(np.quantile(stats, 1 - alpha / 2))


def summarize(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """One row per (model, metric) with central tendency, dispersion, percentiles and 95% CI.

    Statistics are computed on successful replicates only; the share of failed ones is
    reported next to them in 'error_rate', so nothing disappears without a trace.
    """
    errors = error_rates(df).set_index("model")
    rows = []
    for model, g in df.groupby("model", sort=True):
        ok = g[g["status"] == "ok"]
        for col, label in METRICS.items():
            v = ok[col].dropna()
            if col == "coef_robot":
                ci_low, ci_high = v.quantile(0.025), v.quantile(0.975)
                ci_method = "percentile bootstrap of beta_1 (states resampled)"
            else:
                ci_low, ci_high = bootstrap_ci(v.to_numpy(), seed=seed)
                ci_method = "bootstrap CI of the median"
            rows.append({
                "model": model,
                "metric": col,
                "description": label,
                "n": len(v),
                "mean": v.mean(),
                "sd": v.std(ddof=1),
                "median": v.median(),
                "p25": v.quantile(0.25),
                "p75": v.quantile(0.75),
                "p95": v.quantile(0.95),
                "p99": v.quantile(0.99),
                "ci95_low": ci_low,
                "ci95_high": ci_high,
                "ci_method": ci_method,
                "share_below_zero": float((v < 0).mean()) if col == "coef_robot" else np.nan,
                "n_outliers_iqr": int(g.loc[v.index, f"{col}_outlier"].sum()),
                "error_rate": float(errors.loc[model, "error_rate"]),
            })
    return pd.DataFrame(rows)


def describe_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Descriptive statistics of the study variables, in the units used in the README."""
    variables = {
        "robot": "Robot exposure (% of employees)",
        "real_pay": "Real average annual pay (2021 US$)",
        "nominal_pay": "Nominal average annual pay (US$)",
        "employment": "Manufacturing employment (persons)",
        "establishments": "Manufacturing establishments (count)",
    }
    rows = []
    for col, label in variables.items():
        if col not in panel.columns:
            continue
        v = panel[col].dropna()
        rows.append({"variable": col, "description": label, "n": len(v), "mean": v.mean(), "sd": v.std(ddof=1),
                     "median": v.median(), "p25": v.quantile(0.25), "p75": v.quantile(0.75),
                     "min": v.min(), "max": v.max()})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean and aggregate the bootstrap log")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--panel", default="data/processed/panel.csv")
    parser.add_argument("--out-dir", default="data/processed")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    seed = int(cfg["project"]["random_seed"])
    np.random.seed(seed)
    out_dir = resolve(cfg, args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = load_log(resolve(cfg, cfg["benchmark"]["output"]))
    bench = flag_outliers(drop_warmup(raw))
    summary = summarize(bench, seed=seed)

    summary.to_csv(out_dir / "metrics_summary.csv", index=False, float_format="%.6f")
    bench.to_csv(out_dir / "benchmark_clean.csv", index=False, float_format="%.6f")

    panel_path = resolve(cfg, args.panel)
    if panel_path.is_file():
        describe_panel(pd.read_csv(panel_path)).to_csv(out_dir / "descriptive_stats.csv", index=False,
                                                       float_format="%.4f")

    limit = cfg["guardrails"].get("max_bootstrap_error_rate", 0.05)
    print(f"records: {len(raw)} total, {len(raw) - len(bench)} warm-up dropped, {len(bench)} kept")
    pd.set_option("display.width", 200)
    cols = ["model", "metric", "n", "mean", "sd", "median", "p95", "p99", "ci95_low", "ci95_high", "n_outliers_iqr"]
    print(summary[cols].round(6).to_string(index=False))
    for _, r in error_rates(bench).iterrows():
        status = "PASS" if r["error_rate"] <= limit else "FLAG"
        print(f"guardrail | {r['model']} error rate {r['error_rate']:.2%} (<= {limit:.0%}) | {status}")
    print(f"saved: {out_dir / 'metrics_summary.csv'}")
    print(json.dumps({"files": sorted(p.name for p in out_dir.glob('*.csv'))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
