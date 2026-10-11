"""End-to-end test: the pipeline runs on data/sample and produces the documented outputs."""

from pathlib import Path

import numpy as np
import pytest

from src.config import load_config
from src.main import compute, main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return load_config(ROOT / "config.yaml")


def test_sample_panel_shape(cfg):
    out = compute(cfg)
    assert out["info"]["panel_rows"] == 10
    assert out["info"]["robot_flagged_s"] == 1          # the Ohio 2018 cell
    assert out["panel"]["state"].nunique() == 5


def test_m0_and_m1_use_the_same_sample(cfg):
    res = compute(cfg)["results"].set_index("model")
    assert res.loc["M0", "n_obs"] == res.loc["M1", "n_obs"]
    assert res.loc["R2", "n_obs"] == res.loc["M1", "n_obs"] - 1   # R2 drops the (s)-flagged cell


def test_primary_metric_is_finite_and_consistent(cfg):
    m1 = compute(cfg)["results"].set_index("model").loc["M1"]
    assert m1["status"] == "ok"
    assert np.isfinite([m1["coef"], m1["std_err"], m1["p_value"]]).all()
    assert m1["ci_low"] < m1["coef"] < m1["ci_high"]
    assert 0 <= m1["p_value"] <= 1
    assert m1["pct_change_per_pp"] == pytest.approx(100 * m1["coef"], abs=1e-4)


def test_guardrails_are_reported(cfg):
    g = compute(cfg)["guardrails"]
    assert {"VIF (max over regressors)", "Breusch-Pagan p-value", "Jarque-Bera p-value",
            "Min states per year in M1 sample", "Share of withheld robot cells"} <= set(g["check"])


def test_two_runs_give_identical_tables(cfg):
    a, b = compute(cfg), compute(cfg)
    assert a["results"].equals(b["results"])
    assert a["guardrails"].equals(b["guardrails"])


def test_cli_writes_outputs(tmp_path):
    code = main(["--config", str(ROOT / "config.yaml"), "--output-dir", str(tmp_path / "out")])
    assert code == 0
    for name in ("results_table.csv", "guardrails.csv", "summary.md", "run.log", "qq_plot.png", "panel_used.csv"):
        assert (tmp_path / "out" / name).is_file(), name
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "SAMPLE RUN" in summary                       # a sample run can never be mistaken for a result
    assert "identical" in (tmp_path / "out" / "guardrails.csv").read_text(encoding="utf-8")


def test_cli_fails_cleanly_when_inputs_are_missing(tmp_path):
    cfg_text = (ROOT / "config.yaml").read_text(encoding="utf-8").replace("mode: sample", "mode: full")
    bad = tmp_path / "config.yaml"
    bad.write_text(cfg_text, encoding="utf-8")            # full mode, but data/raw is empty in this folder
    assert main(["--config", str(bad), "--output-dir", str(tmp_path / "out")]) == 1
