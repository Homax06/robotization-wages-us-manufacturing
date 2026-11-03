"""Tests for the bootstrap measurement harness (src/collector.py), run on the sample data."""

import json
from pathlib import Path

import pandas as pd

from src.collector import run
from src.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def _cfg(n_warmup=3, n_runs=10):
    cfg = load_config(ROOT / "config.yaml")
    cfg["data"]["mode"] = "sample"
    cfg["benchmark"].update(n_warmup=n_warmup, n_runs=n_runs)
    return cfg


def test_jsonl_has_one_valid_record_per_run_and_model(tmp_path):
    out, meta = tmp_path / "run.jsonl", tmp_path / "meta.json"
    run(_cfg(), out, meta)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == (3 + 10) * 2  # (warm-up + benchmark) x (M0, M1)
    records = [json.loads(line) for line in lines]
    assert {r["phase"] for r in records} == {"warmup", "benchmark"}
    assert all(r["status"] in {"ok", "skipped", "rank_deficient", "error"} for r in records)
    assert sum(r["phase"] == "warmup" for r in records) == 3 * 2


def test_summary_excludes_warmup_and_reports_percentiles(tmp_path):
    summary = run(_cfg(), tmp_path / "run.jsonl", tmp_path / "meta.json")
    assert set(summary["model"]) == {"M0", "M1"}
    assert (summary["n_runs"] == 10).all()  # warm-up replicates are not counted
    for col in ("error_rate", "coef_median", "coef_ci95_low", "coef_ci95_high", "runtime_ms_p95", "runtime_ms_p99"):
        assert col in summary.columns


def test_same_seed_gives_identical_coefficients(tmp_path):
    run(_cfg(), tmp_path / "a.jsonl", tmp_path / "a.json")
    run(_cfg(), tmp_path / "b.jsonl", tmp_path / "b.json")
    a = pd.read_json(tmp_path / "a.jsonl", lines=True)
    b = pd.read_json(tmp_path / "b.jsonl", lines=True)
    pd.testing.assert_series_equal(a["coef_robot"], b["coef_robot"])


def test_metadata_records_environment(tmp_path):
    meta_path = tmp_path / "meta.json"
    run(_cfg(), tmp_path / "run.jsonl", meta_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in ("python", "os", "cpu", "packages", "random_seed", "inputs", "finished_at"):
        assert key in meta
