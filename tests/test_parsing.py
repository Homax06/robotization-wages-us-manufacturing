"""Unit tests for the data-loading layer (cell parser, Census workbook, QCEW filters, CPI)."""

import math
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from src.load_data import add_real_pay, load_cpi, load_qcew, load_robots_xlsx, parse_exposure_cell


# ---------- Census cell parser ----------

@pytest.mark.parametrize(
    "raw, expected_value, expected_flag",
    [
        (0.278, 27.8, False),          # fraction -> percentage points
        ("0.278", 27.8, False),        # same, but as text (CSV sample)
        ("32.5%(s)", 32.5, True),      # percent text, standard error > 40%
        ("0.0%(s)", 0.0, True),
        ("12.5%", 12.5, False),
        (0, 0.0, False),
    ],
)
def test_parse_numeric_cells(raw, expected_value, expected_flag):
    value, flag = parse_exposure_cell(raw)
    assert value == pytest.approx(expected_value)
    assert flag is expected_flag


@pytest.mark.parametrize("raw", ["D", "S", "A", "", None, float("nan")])
def test_parse_suppressed_cells_are_missing(raw):
    value, flag = parse_exposure_cell(raw)
    assert math.isnan(value) and flag is False


def test_parse_rejects_unknown_text_and_bad_units():
    with pytest.raises(ValueError):
        parse_exposure_cell("see note 3")
    with pytest.raises(ValueError):
        parse_exposure_cell(27.8)  # already in percent: would silently be 2780 pp


# ---------- Census workbook layout ----------

def _make_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Percent of... Geo"
    ws.append(["Percent of Plants with Robots and Percent of Employees Exposed to Robots by Geographic Area"])
    ws.append(["Source: 2018-2021 Annual Survey of Manufactures"])
    ws.append(["Experimental Data Product"])
    ws.append([])
    ws.append(["Geographic Area Name", "2021 Percent of Employees Exposed to Robots", "2018 Percent of Employees Exposed to Robots",
               "2021 Standard Error for Percent of Employees Exposed to Robots"])
    ws.append(["United States", 0.278, 0.232, 0.6])
    ws.append(["Alabama", 0.286, 0.28, 1.9])
    ws.append(["Hawaii", "S", "D", "A"])
    ws.append(["Ohio", 0.375, "32.5%(s)", 4.2])
    ws.append([])
    ws.append(["Data Management System (DMS) number: P-7500114"])
    wd = wb.create_sheet("Percent of... Geo demean")
    for _ in range(4):
        wd.append([])
    wd.append(["Geographic Area Name", "2021 Demeaned Percent of Employees Exposed to Robots", "2018 Demeaned Percent of Employees Exposed to Robots"])
    wd.append(["Alabama", 0.269, 0.243])
    wd.append(["Hawaii", "D", "D"])
    wd.append(["Ohio", 0.313, 0.287])
    wb.save(path)


def test_load_robots_xlsx(tmp_path):
    f = tmp_path / "ASM Robotics.xlsx"
    _make_workbook(f)
    df = load_robots_xlsx(f, "Percent of... Geo", "Percent of... Geo demean", (2018, 2021), exclude=["Hawaii"])
    assert sorted(df["state"].unique()) == ["Alabama", "Ohio"]        # US total and excluded area removed
    assert len(df) == 4                                                # 2 states x 2 years
    ohio18 = df[(df["state"] == "Ohio") & (df["year"] == 2018)].iloc[0]
    assert ohio18["exposure_pct"] == pytest.approx(32.5) and bool(ohio18["exposure_flagged"])
    assert ohio18["demeaned_pct"] == pytest.approx(28.7)
    al21 = df[(df["state"] == "Alabama") & (df["year"] == 2021)].iloc[0]
    assert al21["exposure_pct"] == pytest.approx(28.6)


def test_load_robots_xlsx_keeps_withheld_cells_as_missing(tmp_path):
    f = tmp_path / "ASM Robotics.xlsx"
    _make_workbook(f)
    df = load_robots_xlsx(f, "Percent of... Geo", "Percent of... Geo demean", (2018, 2021), exclude=[])
    hawaii = df[df["state"] == "Hawaii"]
    assert hawaii["exposure_pct"].isna().all()


# ---------- QCEW filters ----------

def _qcew_rows():
    cols = ["area_fips", "own_code", "industry_code", "year", "annual_avg_estabs", "annual_avg_emplvl", "avg_annual_pay"]
    return pd.DataFrame(
        [
            ["01000", 5, "31-33", 2019, 3000, 270000, 55000],   # keep
            ["01000", 0, "31-33", 2019, 3100, 280000, 56000],   # all ownerships -> drop
            ["01000", 5, "10", 2019, 99999, 9999999, 99999],    # other industry -> drop
            ["US000", 5, "31-33", 2019, 300000, 12000000, 70000],   # national -> drop
            ["01001", 5, "31-33", 2019, 100, 5000, 50000],      # county -> drop
            ["72000", 5, "31-33", 2019, 100, 5000, 50000],      # Puerto Rico -> drop
            ["26000", 5, "31-33", 2017, 9000, 600000, 68000],   # outside period -> drop
            ["26000", 5, "31-33", 2020, 8900, 590000, 70000],   # keep
        ],
        columns=cols,
    )


def test_load_qcew_filters(tmp_path):
    f = tmp_path / "q.csv"
    _qcew_rows().to_csv(f, index=False)
    df = load_qcew(f, "31-33", "5", (2018, 2021))
    assert set(zip(df["state"], df["year"])) == {("Alabama", 2019), ("Michigan", 2020)}
    assert {"establishments", "employment", "nominal_pay"} <= set(df.columns)


def test_load_qcew_reads_a_folder_and_checks_duplicates(tmp_path):
    rows = _qcew_rows()
    rows.iloc[[0]].to_csv(tmp_path / "a.csv", index=False)
    rows.iloc[[0]].to_csv(tmp_path / "b.csv", index=False)   # same state-year twice
    with pytest.raises(ValueError, match="Duplicate"):
        load_qcew(tmp_path, "31-33", "5", (2018, 2021))


def test_load_qcew_requires_columns(tmp_path):
    f = tmp_path / "q.csv"
    _qcew_rows().drop(columns=["avg_annual_pay"]).to_csv(f, index=False)
    with pytest.raises(KeyError, match="avg_annual_pay"):
        load_qcew(f, "31-33", "5", (2018, 2021))


# ---------- CPI / real pay ----------

def test_real_pay_uses_base_year(tmp_path):
    f = tmp_path / "cpi.csv"
    f.write_text("year,cpi_u\n2018,100\n2021,200\n")
    q = pd.DataFrame({"state": ["A", "A"], "year": [2018, 2021], "establishments": [1, 1], "employment": [1, 1], "nominal_pay": [50.0, 100.0]})
    out = add_real_pay(q, load_cpi(f), base_year=2021)
    # 2018 pay is scaled up by 200/100, the base year is unchanged
    assert out["real_pay"].tolist() == pytest.approx([100.0, 100.0])


def test_real_pay_fails_loudly_without_cpi(tmp_path):
    f = tmp_path / "cpi.csv"
    f.write_text("year,cpi_u\n2021,200\n")
    q = pd.DataFrame({"state": ["A"], "year": [2018], "establishments": [1], "employment": [1], "nominal_pay": [50.0]})
    with pytest.raises(ValueError, match="CPI is missing"):
        add_real_pay(q, load_cpi(f), base_year=2021)
