"""Command-line entry point.

    python -m src.main --config config.yaml

Runs the whole analysis, writes tables, a Q-Q plot, a summary and a log into the output
folder, then repeats the computation once to verify that the results are identical.
"""

from __future__ import annotations

import argparse
import logging
import platform
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
import statsmodels

from . import __version__
from .analysis import qq_plot, run_guardrails, run_models
from .config import load_config, resolve, sha256_file, sha256_text
from .load_data import build_panel

log = logging.getLogger("robots_wages")


def compute(cfg: dict) -> dict:
    """Pure computation: read inputs, fit models, run guardrails. No files are written here."""
    panel, info = build_panel(cfg)
    results, m1 = run_models(panel, cfg)
    guardrails = run_guardrails(m1, info, panel, cfg)
    return {
        "panel": panel,
        "info": info,
        "results": results.round(6),
        "guardrails": guardrails,
        "m1": m1,
    }


def _csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, float_format="%.6f")


def _decision(results: pd.DataFrame, alpha: float, mode: str) -> str:
    m1 = results.loc[results["model"] == "M1"].iloc[0]
    if m1["status"] != "ok":
        return f"M1 was not estimated ({m1['status']})."
    verdict = "REJECT H0" if m1["p_value"] < alpha else "FAIL TO REJECT H0"
    text = (
        f"{verdict} at alpha = {alpha}: b1 = {m1['coef']:.4f} (p = {m1['p_value']:.4f}), "
        f"i.e. {m1['pct_change_per_pp']:+.2f}% change in real wages per +1 percentage point of robot exposure."
    )
    if mode == "sample":
        text += "  [SAMPLE RUN: synthetic wage data, not a research result]"
    return text


def write_outputs(cfg: dict, out: dict, out_dir: Path, repro_ok: bool | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    results, guard, info = out["results"], out["guardrails"].copy(), out["info"]

    if repro_ok is not None:
        guard.loc[len(guard)] = {
            "check": "Pipeline reproducibility (two runs)", "value": "identical" if repro_ok else "different",
            "criterion": "identical result tables", "status": "PASS" if repro_ok else "FLAG",
        }

    (out_dir / "results_table.csv").write_text(_csv(results), encoding="utf-8")
    (out_dir / "guardrails.csv").write_text(_csv(guard), encoding="utf-8")
    out["panel"].to_csv(out_dir / "panel_used.csv", index=False, float_format="%.6f")
    qq_plot(out["m1"], out_dir / "qq_plot.png")

    decision = _decision(results, float(cfg["model"]["alpha"]), info["mode"])
    lines = [
        "# Run summary", "",
        f"- Mode: **{info['mode']}**" + ("  (smoke test on synthetic wages)" if info["mode"] == "sample" else ""),
        f"- Panel rows used: {info['panel_rows']} (robot cells read: {info['robot_cells']}, "
        f"withheld: {info['robot_withheld']}, flagged (s): {info['robot_flagged_s']})",
        f"- Decision: {decision}", "", "## Models", "", _md_table(results),
        "", "## Guardrails", "", _md_table(guard), "",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _md_table(df: pd.DataFrame) -> str:
    """Minimal Markdown table (avoids an extra dependency)."""
    def cell(v):
        return "" if pd.isna(v) else (f"{v:.4f}" if isinstance(v, float) else str(v))

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join(["---"] * len(df.columns)) + "|"
    body = ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep] + body)


def setup_logging(log_file: Path | None) -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        handler.setFormatter(fmt)
        log.addHandler(handler)


def log_environment(cfg: dict) -> None:
    mode = cfg["data"]["mode"]
    log.info("project=%s | pipeline_version=%s", cfg["project"]["title"], __version__)
    log.info("python=%s | platform=%s", platform.python_version(), platform.platform())
    log.info("numpy=%s pandas=%s scipy=%s statsmodels=%s", np.__version__, pd.__version__, scipy.__version__, statsmodels.__version__)
    log.info("config=%s sha256=%s", cfg["_config_path"], sha256_file(cfg["_config_path"])[:16])
    log.info("random_seed=%s | data.mode=%s | years=%s-%s", cfg["project"]["random_seed"], mode,
             cfg["study"]["start_year"], cfg["study"]["end_year"])
    for key, rel in cfg["data"][mode].items():
        if isinstance(rel, str) and ("." in Path(rel).name or key == "qcew"):
            path = resolve(cfg, rel)
            if path.is_file():
                log.info("input %-12s %s sha256=%s", key, rel, sha256_file(path)[:16])
            elif path.is_dir():
                files = sorted(path.glob("*.csv"))
                log.info("input %-12s %s (%d csv files)", key, rel, len(files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Robotization and wages: reproducible analysis pipeline")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml (default: ./config.yaml)")
    parser.add_argument("--mode", choices=["sample", "full"], help="override data.mode from the config")
    parser.add_argument("--output-dir", help="override output.dir from the config")
    parser.add_argument("--skip-repro-check", action="store_true", help="do not repeat the run to compare results")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.mode:
        cfg["data"]["mode"] = args.mode
    out_dir = resolve(cfg, args.output_dir) if args.output_dir else resolve(cfg, cfg["output"]["dir"])
    setup_logging(out_dir / "run.log")

    started = time.perf_counter()
    try:
        np.random.seed(int(cfg["project"]["random_seed"]))
        log_environment(cfg)
        out = compute(cfg)
        log.info("panel built: %s", out["info"])

        repro_ok = None
        if not args.skip_repro_check:
            again = compute(cfg)
            h1 = sha256_text(_csv(out["results"]) + _csv(out["guardrails"]))
            h2 = sha256_text(_csv(again["results"]) + _csv(again["guardrails"]))
            repro_ok = h1 == h2
            log.info("reproducibility check: %s (sha256 %s)", "identical" if repro_ok else "DIFFERENT", h1[:16])

        write_outputs(cfg, out, out_dir, repro_ok)
        for _, r in out["results"].iterrows():
            log.info("%s | %s | n=%s | coef=%.4f p=%.4f", r["model"], r["status"], r["n_obs"],
                     r["coef"] if pd.notna(r["coef"]) else float("nan"),
                     r["p_value"] if pd.notna(r["p_value"]) else float("nan"))
        for _, r in out["guardrails"].iterrows():
            log.info("guardrail | %s | %s | %s", r["check"], r["value"], r["status"])
        log.info("decision: %s", _decision(out["results"], float(cfg["model"]["alpha"]), out["info"]["mode"]))
        log.info("outputs written to %s | runtime %.2f s", out_dir, time.perf_counter() - started)
    except Exception:
        log.exception("run failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
