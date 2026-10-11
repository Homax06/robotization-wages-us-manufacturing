"""Loading and cleaning of the three inputs and building the state x year panel.

Inputs
------
* Robot exposure: US Census Bureau, Annual Survey of Manufactures (ASM), robotics tables.
* Wages, employment, establishments: BLS QCEW annual-average files.
* CPI-U: annual averages, to turn nominal pay into real pay.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

from .config import resolve
from .states import STATE_FIPS

# "17.6%(s)" -> 17.6 percentage points, flagged (standard error above 40% of the estimate)
_PCT_FLAGGED = re.compile(r"^([0-9]*\.?[0-9]+)\s*%\s*\(s\)$")
_PCT_PLAIN = re.compile(r"^([0-9]*\.?[0-9]+)\s*%$")
# Suppression codes used by the Census Bureau: the value is missing.
_SUPPRESSED = {"D", "S", "A", "X", "NA", "N/A", "(D)", "(S)", "-", "--"}


def _from_fraction(value: float) -> float:
    """Census publishes shares as fractions (0.278 = 27.8%). Return percentage points."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"Share {value!r} is outside [0, 1]; check the units of the source table.")
    return value * 100.0


def parse_exposure_cell(raw) -> tuple[float, bool]:
    """Parse one cell of the Census robotics table.

    Returns ``(value_in_percentage_points, flagged)``. ``flagged`` is True for cells marked "(s)".
    Suppressed cells (D, S, A, ...) and empty cells return ``(nan, False)``.
    Unknown text raises ValueError, so a changed table layout cannot pass silently.
    """
    if raw is None:
        return math.nan, False
    if isinstance(raw, (int, float, np.integer, np.floating)):
        if isinstance(raw, float) and math.isnan(raw):
            return math.nan, False
        return _from_fraction(float(raw)), False

    text = str(raw).strip()
    if text == "" or text.lower() == "nan":
        return math.nan, False
    match = _PCT_FLAGGED.match(text)
    if match:
        return float(match.group(1)), True
    match = _PCT_PLAIN.match(text)
    if match:
        return float(match.group(1)), False
    if text.upper() in _SUPPRESSED:
        return math.nan, False
    try:
        return _from_fraction(float(text)), False
    except ValueError as exc:
        if "outside" in str(exc):
            raise
    raise ValueError(f"Unrecognised cell in robotics table: {raw!r}")


def _records_to_frame(records: list[dict], years: tuple[int, int], exclude: list[str]) -> pd.DataFrame:
    """records: dicts with state, year, exposure_raw, demeaned_raw -> tidy parsed frame."""
    rows = []
    for rec in records:
        exposure, flagged = parse_exposure_cell(rec["exposure_raw"])
        demeaned, _ = parse_exposure_cell(rec.get("demeaned_raw"))
        rows.append(
            {
                "state": str(rec["state"]).strip(),
                "year": int(rec["year"]),
                "exposure_pct": exposure,
                "exposure_flagged": flagged,
                "demeaned_pct": demeaned,
            }
        )
    df = pd.DataFrame(rows)
    df = df[(df["year"] >= years[0]) & (df["year"] <= years[1])]
    df = df[~df["state"].isin(exclude + ["United States"])]
    if df.duplicated(["state", "year"]).any():
        raise ValueError("Duplicate state-year rows in the robotics table.")
    return df.reset_index(drop=True)


def load_robots_csv(path: Path, years: tuple[int, int], exclude: list[str]) -> pd.DataFrame:
    """Sample format: columns state, year, exposure_raw, demeaned_raw (raw cell text)."""
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = {"state", "year", "exposure_raw"} - set(raw.columns)
    if missing:
        raise KeyError(f"{path.name}: missing columns {sorted(missing)}")
    if "demeaned_raw" not in raw.columns:
        raw["demeaned_raw"] = ""
    return _records_to_frame(raw.to_dict("records"), years, exclude)


def _read_sheet_table(ws, label: str) -> dict[tuple[str, int], object]:
    """Read ``{(area, year): raw_cell}`` from an ASM sheet whose header starts with
    'Geographic Area Name' and whose columns are named '<year> ... <label> ...'."""
    rows = list(ws.iter_rows(values_only=True))
    header_idx = next(
        (i for i, r in enumerate(rows) if r and isinstance(r[0], str) and r[0].strip() == "Geographic Area Name"),
        None,
    )
    if header_idx is None:
        raise ValueError(f"Sheet {ws.title!r}: header row 'Geographic Area Name' not found.")
    header = rows[header_idx]

    year_cols: dict[int, int] = {}
    for j, name in enumerate(header):
        if not isinstance(name, str):
            continue
        m = re.match(rf"^(\d{{4}})\s+{re.escape(label)}\s*$", name.strip())
        if m:
            year_cols[int(m.group(1))] = j
    if not year_cols:
        raise ValueError(f"Sheet {ws.title!r}: no columns named '<year> {label}'.")

    out: dict[tuple[str, int], object] = {}
    for r in rows[header_idx + 1 :]:
        if not r or r[0] is None or not isinstance(r[0], str) or r[0].startswith("Data Management"):
            break
        for year, j in year_cols.items():
            out[(r[0].strip(), year)] = r[j] if j < len(r) else None
    return out


def load_robots_xlsx(
    path: Path, sheet_exposure: str, sheet_demeaned: str, years: tuple[int, int], exclude: list[str]
) -> pd.DataFrame:
    """Full format: the Census workbook 'ASM Robotics.xlsx'."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        exposure = _read_sheet_table(wb[sheet_exposure], "Percent of Employees Exposed to Robots")
        demeaned = _read_sheet_table(wb[sheet_demeaned], "Demeaned Percent of Employees Exposed to Robots")
    finally:
        wb.close()
    records = [
        {"state": area, "year": year, "exposure_raw": cell, "demeaned_raw": demeaned.get((area, year))}
        for (area, year), cell in exposure.items()
    ]
    return _records_to_frame(records, years, exclude)


def load_qcew(path: Path, naics: str, own_code: str, years: tuple[int, int]) -> pd.DataFrame:
    """Read QCEW annual CSV file(s) and keep state-level rows of one industry and ownership."""
    files = [path] if path.is_file() else sorted(path.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No QCEW CSV files found in {path}")
    need = ["area_fips", "own_code", "industry_code", "year", "annual_avg_estabs", "annual_avg_emplvl", "avg_annual_pay"]
    optional = ["size_code", "disclosure_code"]
    str_cols = {c: str for c in ("area_fips", "own_code", "industry_code", "size_code", "disclosure_code")}

    frames = []
    for f in files:
        header = pd.read_csv(f, nrows=0).columns.str.strip()
        missing = [c for c in need if c not in header]
        if missing:
            raise KeyError(f"{f.name}: missing QCEW columns {missing}")
        use = need + [c for c in optional if c in header]
        frames.append(pd.read_csv(f, usecols=use, dtype=str_cols))
    df = pd.concat(frames, ignore_index=True)

    df["industry_code"] = df["industry_code"].str.strip().str.replace("_", "-", regex=False)
    df["own_code"] = df["own_code"].str.strip()
    df["area_fips"] = df["area_fips"].str.strip().str.zfill(5)
    df["year"] = pd.to_numeric(df["year"]).astype(int)

    keep = (
        (df["industry_code"] == naics)
        & (df["own_code"] == str(own_code))
        & (df["area_fips"].str[2:] == "000")
        & df["area_fips"].str[:2].isin(STATE_FIPS.keys())
        & df["year"].between(*years)
    )
    if "size_code" in df.columns:
        keep &= df["size_code"].fillna("0").str.strip() == "0"
    if "disclosure_code" in df.columns:
        keep &= df["disclosure_code"].fillna("").str.strip() != "N"  # N = not disclosed
    df = df[keep].copy()

    if df.duplicated(["area_fips", "year"]).any():
        raise ValueError("Duplicate state-year rows in QCEW after filtering; check industry/ownership/size codes.")

    df["state"] = df["area_fips"].str[:2].map(STATE_FIPS)
    for col in ("annual_avg_estabs", "annual_avg_emplvl", "avg_annual_pay"):
        df[col] = pd.to_numeric(df[col])
    out = df.rename(
        columns={"annual_avg_estabs": "establishments", "annual_avg_emplvl": "employment", "avg_annual_pay": "nominal_pay"}
    )[["state", "year", "establishments", "employment", "nominal_pay"]]
    return out.reset_index(drop=True)


def load_cpi(path: Path) -> pd.DataFrame:
    """CSV with columns year, cpi_u."""
    cpi = pd.read_csv(path)
    cpi.columns = cpi.columns.str.strip()
    if not {"year", "cpi_u"} <= set(cpi.columns):
        raise KeyError(f"{path.name}: expected columns 'year' and 'cpi_u'")
    cpi["year"] = cpi["year"].astype(int)
    if cpi["year"].duplicated().any():
        raise ValueError("Duplicate years in the CPI file.")
    return cpi[["year", "cpi_u"]]


def add_real_pay(qcew: pd.DataFrame, cpi: pd.DataFrame, base_year: int) -> pd.DataFrame:
    """real pay = nominal pay x CPI(base year) / CPI(year)."""
    if base_year not in set(cpi["year"]):
        raise ValueError(f"CPI base year {base_year} is not in the CPI file.")
    base = float(cpi.loc[cpi["year"] == base_year, "cpi_u"].iloc[0])
    merged = qcew.merge(cpi, on="year", how="left", validate="many_to_one")
    if merged["cpi_u"].isna().any():
        bad = sorted(merged.loc[merged["cpi_u"].isna(), "year"].unique().tolist())
        raise ValueError(f"CPI is missing for years {bad}.")
    merged["real_pay"] = merged["nominal_pay"] * base / merged["cpi_u"]
    return merged


def build_panel(cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Read all inputs and return (panel, info). ``info`` holds coverage numbers for the guardrails."""
    study = cfg["study"]
    years = (int(study["start_year"]), int(study["end_year"]))
    exclude = list(study.get("exclude_areas", []))
    mode = cfg["data"]["mode"]
    if mode not in ("sample", "full"):
        raise ValueError("data.mode must be 'sample' or 'full'")
    src = cfg["data"][mode]

    if mode == "sample":
        robots = load_robots_csv(resolve(cfg, src["robots"]), years, exclude)
    else:
        robots = load_robots_xlsx(
            resolve(cfg, src["robots_xlsx"]), src["robots_sheet_exposure"], src["robots_sheet_demeaned"], years, exclude
        )
    qcew = load_qcew(resolve(cfg, src["qcew"]), study["naics_sector"], study["own_code"], years)
    qcew = add_real_pay(qcew, load_cpi(resolve(cfg, src["cpi"])), int(study["cpi_base_year"]))

    panel = robots.merge(qcew, on=["state", "year"], how="inner", validate="one_to_one")
    panel = panel[panel["real_pay"] > 0].copy()
    panel["robot"] = panel["exposure_pct"]
    panel["robot_demeaned"] = panel["demeaned_pct"]
    panel["ln_wage_real"] = np.log(panel["real_pay"])
    panel["ln_employment"] = np.log(panel["employment"])
    panel["ln_establishments"] = np.log(panel["establishments"])
    panel = panel.sort_values(["state", "year"]).reset_index(drop=True)

    robot_cells = len(robots)
    info = {
        "mode": mode,
        "robot_cells": robot_cells,
        "robot_withheld": int((robots["exposure_pct"].isna()).sum()),
        "robot_flagged_s": int(robots["exposure_flagged"].sum()),
        "robot_states_without_wages": int(len(robots) - len(panel)),
        "panel_rows": int(len(panel)),
    }
    info["withheld_share"] = info["robot_withheld"] / robot_cells if robot_cells else math.nan
    return panel, info
