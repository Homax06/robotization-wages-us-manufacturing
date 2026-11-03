"""Tests for src/process_data.py on a small synthetic log."""

import numpy as np
import pandas as pd

from src.process_data import drop_warmup, error_rates, flag_outliers, summarize


def _log():
    rows = []
    for run_id in range(12):
        for model in ("M0", "M1"):
            rows.append({"run_id": run_id, "phase": "warmup" if run_id < 2 else "benchmark", "model": model,
                         "status": "ok", "coef_robot": -0.004 + 0.0001 * run_id, "runtime_ms": 3.0 + 0.01 * run_id})
    df = pd.DataFrame(rows)
    df.loc[(df["run_id"] == 5) & (df["model"] == "M1"), ["status", "coef_robot"]] = ["error", np.nan]
    df.loc[(df["run_id"] == 6) & (df["model"] == "M0"), "runtime_ms"] = 500.0  # obvious outlier
    return df


def test_warmup_is_dropped():
    bench = drop_warmup(_log())
    assert (bench["phase"] == "benchmark").all() and len(bench) == 20


def test_errors_are_counted_not_hidden():
    rates = error_rates(drop_warmup(_log())).set_index("model")
    assert rates.loc["M1", "n_failed"] == 1 and rates.loc["M1", "error_rate"] == 0.1
    assert rates.loc["M0", "error_rate"] == 0.0


def test_outliers_are_flagged_but_kept():
    bench = flag_outliers(drop_warmup(_log()))
    assert len(bench) == 20  # nothing deleted
    assert bench.loc[bench["runtime_ms"] == 500.0, "runtime_ms_outlier"].all()


def test_summary_has_percentiles_and_ci():
    s = summarize(flag_outliers(drop_warmup(_log())))
    assert set(s["model"]) == {"M0", "M1"}
    for col in ("median", "p95", "p99", "ci95_low", "ci95_high", "error_rate"):
        assert s[col].notna().all()
    assert (s["ci95_low"] <= s["median"]).all() and (s["median"] <= s["ci95_high"]).all()
