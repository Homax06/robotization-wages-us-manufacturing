"""Regression models (baseline M0, main M1, robustness checks) and guardrail diagnostics.

Dependent variable: ln(real average annual pay), state i, year t.
Primary quantity:   the coefficient on robot exposure (percentage points of employees exposed to robots).
Standard errors:    clustered by state.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import jarque_bera

Y = "ln_wage_real"


@dataclass
class Fit:
    """One fitted model plus everything the guardrails need."""

    row: dict
    result: object | None = None
    data: pd.DataFrame | None = None
    exog: pd.DataFrame | None = None


def _design(df: pd.DataFrame, numeric: list[str], year_fx: bool, state_fx: bool) -> pd.DataFrame:
    x = df[numeric].astype(float).copy()
    if year_fx:
        x = x.join(pd.get_dummies(df["year"].astype(int), prefix="year", drop_first=True, dtype=float))
    if state_fx:
        x = x.join(pd.get_dummies(df["state"], prefix="state", drop_first=True, dtype=float))
    return sm.add_constant(x, has_constant="add")


def fit_model(
    panel: pd.DataFrame,
    name: str,
    description: str,
    robot_col: str,
    covariates: list[str],
    cfg: dict,
    year_fx: bool,
    state_fx: bool = False,
    sample: pd.DataFrame | None = None,
) -> Fit:
    """OLS with cluster-robust standard errors. Returns a row for the results table."""
    model_cfg = cfg["model"]
    cluster = model_cfg["cluster_by"]
    base = panel if sample is None else sample
    d = base.dropna(subset=[Y, robot_col] + covariates).reset_index(drop=True)

    row = {
        "model": name,
        "description": description,
        "status": "ok",
        "n_obs": len(d),
        "n_states": int(d["state"].nunique()),
        "coef": np.nan, "std_err": np.nan, "t_stat": np.nan, "p_value": np.nan,
        "ci_low": np.nan, "ci_high": np.nan, "pct_change_per_pp": np.nan,
        "adj_r2": np.nan, "rmse": np.nan,
    }
    x = _design(d, [robot_col] + covariates, year_fx, state_fx) if len(d) else None
    df_resid = (len(d) - x.shape[1]) if x is not None else -1
    min_df = int(model_cfg.get("min_df_resid", 2))
    if len(d) == 0 or df_resid < min_df:
        row["status"] = f"skipped: residual df {df_resid} < {min_df}"
        return Fit(row)

    groups = pd.factorize(d[cluster])[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        res = sm.OLS(d[Y], x).fit(cov_type="cluster", cov_kwds={"groups": groups}, use_t=True)
    ci = res.conf_int(alpha=float(model_cfg["alpha"])).loc[robot_col]
    coef = float(res.params[robot_col])
    row.update(
        coef=coef,
        std_err=float(res.bse[robot_col]),
        t_stat=float(res.tvalues[robot_col]),
        p_value=float(res.pvalues[robot_col]),
        ci_low=float(ci.iloc[0]),
        ci_high=float(ci.iloc[1]),
        pct_change_per_pp=100.0 * coef,
        adj_r2=float(res.rsquared_adj),
        rmse=float(np.sqrt(np.mean(np.square(res.resid)))),
    )
    return Fit(row, res, d, x)


def run_models(panel: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, Fit]:
    """Baseline M0, main M1 and robustness checks R1-R3. Returns (results table, M1 fit)."""
    covs = list(cfg["model"]["covariates"])
    year_fx = bool(cfg["model"]["year_effects"])

    # M0 and M1 are estimated on the SAME sample (rows complete for every variable of M1).
    common = panel.dropna(subset=[Y, "robot"] + covs).reset_index(drop=True)

    m0 = fit_model(panel, "M0", "Baseline: ln(real wage) on robot exposure only", "robot", [], cfg,
                   year_fx=False, sample=common)
    m1 = fit_model(panel, "M1", "Main: + covariates and year effects", "robot", covs, cfg,
                   year_fx=year_fx, sample=common)
    r1 = fit_model(panel, "R1", "Robustness: industry-composition-adjusted (demeaned) exposure", "robot_demeaned",
                   covs, cfg, year_fx=year_fx)
    r2 = fit_model(panel, "R2", "Robustness: drop cells flagged (s)", "robot", covs, cfg, year_fx=year_fx,
                   sample=panel[~panel["exposure_flagged"]])
    r3 = fit_model(panel, "R3", "Robustness: add state fixed effects", "robot", covs, cfg, year_fx=year_fx,
                   state_fx=True, sample=common)

    table = pd.DataFrame([f.row for f in (m0, m1, r1, r2, r3)])
    return table, m1


def run_guardrails(m1: Fit, info: dict, panel: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Diagnostics defined in the Methodology Card. They flag problems; they never discard a result."""
    g = cfg["guardrails"]
    mode = info["mode"]
    rows: list[dict] = []

    def add(check, value, criterion, status):
        rows.append({"check": check, "value": value, "criterion": criterion, "status": status})

    if m1.result is None:
        add("Main model M1", "not estimated", "model must be estimated", m1.row["status"])
        return pd.DataFrame(rows)

    res, exog = m1.result, m1.exog
    regressors = ["robot"] + list(cfg["model"]["covariates"])

    # 1) Multicollinearity
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        vifs = {c: float(variance_inflation_factor(exog.values, list(exog.columns).index(c))) for c in regressors}
    worst = max(vifs.values())
    add("VIF (max over regressors)", round(worst, 4), f"< {g['vif_max']}", "PASS" if worst < g["vif_max"] else "FLAG")

    # 2) Heteroskedasticity: informational, clustered SEs are always used
    try:
        _, bp_p, _, _ = het_breuschpagan(res.resid, exog)
        status = "PASS" if bp_p > g["breusch_pagan_alpha"] else "FLAG (clustered SE used)"
        add("Breusch-Pagan p-value", round(float(bp_p), 6), f"> {g['breusch_pagan_alpha']}", status)
    except Exception as exc:  # tiny samples can break the auxiliary regression
        add("Breusch-Pagan p-value", "n/a", f"> {g['breusch_pagan_alpha']}", f"not computed ({type(exc).__name__})")

    # 3) Residual normality
    _, jb_p, skew, kurt = jarque_bera(res.resid)
    add("Jarque-Bera p-value", round(float(jb_p), 6), f"> {g['jarque_bera_alpha']}",
        "PASS" if jb_p > g["jarque_bera_alpha"] else "FLAG")

    # 4) Sample coverage
    states_per_year = m1.data.groupby("year")["state"].nunique()
    min_states = int(states_per_year.min())
    need = g["min_states_per_year"] if mode == "full" else g["sample_min_states_per_year"]
    add("Min states per year in M1 sample", min_states, f">= {need}" + ("" if mode == "full" else " (relaxed, sample mode)"),
        "PASS" if min_states >= need else "FLAG")
    add("Share of withheld robot cells", round(float(info["withheld_share"]), 4), f"<= {g['max_withheld_share']}",
        "PASS" if info["withheld_share"] <= g["max_withheld_share"] else "FLAG")
    return pd.DataFrame(rows)


def qq_plot(m1: Fit, path) -> None:
    """Q-Q plot of M1 residuals (visual part of the normality check)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if m1.result is None:
        return
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    stats.probplot(m1.result.resid, dist="norm", plot=ax)
    ax.set_title("Q-Q plot of M1 residuals")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
