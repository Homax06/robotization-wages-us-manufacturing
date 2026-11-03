"""Publication-ready figures (Week 8, steps 3-4).

    python -m src.visualize

Input
-----
* data/processed/panel.csv            state x year panel (real wages, robot exposure)
* data/processed/benchmark_clean.csv  bootstrap replicates of M0 and M1 (src/process_data.py)

Output (reports/figures/, every figure as vector .pdf and 300-DPI .png)
------
* fig1_latency_vs_load        primary metric vs load: real wage vs robot exposure, OLS fit + 95% CI band
* fig2_distribution_boxplot   distribution of the bootstrap coefficient, baseline M0 vs main model M1
* fig3_coefficients           beta_1 with 95% CI for M0, M1 and robustness checks R1-R3

The file names of fig1 and fig2 follow the structure required by the Task 3 brief.

Three rules of scientific graphics
----------------------------------
1. Axes:     every axis names the variable and its unit; the wage axis is logarithmic because the
             model is estimated on ln(wage); the coefficient axis is centred on zero (H0).
2. Variance: no bare point estimates. Fig1 has a 95% CI band, fig2 shows the whole bootstrap
             distribution (box = p25-p75, whiskers = 1.5 x IQR) plus the median with its 95% CI,
             fig3 shows 95% CI error bars.
3. Colour:   colorblind-safe palette, and every series also differs by marker / line style /
             hatch, so the figures stay readable in black-and-white print.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter  # noqa: E402

from .analysis import run_models  # noqa: E402
from .config import load_config, resolve  # noqa: E402

PALETTE = sns.color_palette("colorblind")
MARKERS = ["o", "s", "^", "D", "v", "P"]
LINESTYLES = ["-", "--", "-.", ":"]
DPI = 300


def set_style() -> None:
    """Publication theme: white grid, larger fonts, colorblind palette."""
    sns.set_theme(style="whitegrid", font_scale=1.2, palette="colorblind")
    plt.rcParams.update({
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": True,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,  # embed real fonts in the PDF (editable text)
    })


def save(fig: plt.Figure, out_dir: Path, name: str) -> list[Path]:
    """Save one figure as vector PDF and 300-DPI PNG."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{name}.pdf", out_dir / f"{name}.png"]
    fig.savefig(paths[0])
    fig.savefig(paths[1], dpi=DPI)
    plt.close(fig)
    return paths


# ----------------------------------------------------------------------------- figure 1


def fig_wage_vs_exposure(panel: pd.DataFrame, seed: int = 42) -> plt.Figure:
    """Real wage (log axis) against robot exposure, one marker per year, pooled OLS fit + 95% CI."""
    d = panel.dropna(subset=["robot", "real_pay"]).copy()
    d["ln_wage"] = np.log(d["real_pay"])
    fig, ax = plt.subplots(figsize=(9, 5.4))

    for i, (year, g) in enumerate(sorted(d.groupby("year"))):
        ax.scatter(g["robot"], g["real_pay"], s=38, alpha=0.8, marker=MARKERS[i], color=PALETTE[i],
                   edgecolor="black", linewidth=0.4, label=str(year), zorder=3)

    # OLS of ln(wage) on exposure with a bootstrap 95% CI band, drawn back on the dollar scale
    x = d["robot"].to_numpy()
    y = d["ln_wage"].to_numpy()
    grid = np.linspace(x.min(), x.max(), 100)
    slope, intercept = np.polyfit(x, y, 1)
    rng = np.random.default_rng(seed)
    boot = np.empty((1000, grid.size))
    for b in range(boot.shape[0]):
        idx = rng.integers(0, len(x), len(x))
        s, c = np.polyfit(x[idx], y[idx], 1)
        boot[b] = c + s * grid
    low, high = np.percentile(boot, [2.5, 97.5], axis=0)
    ax.fill_between(grid, np.exp(low), np.exp(high), color="0.35", alpha=0.2, label="95% CI (bootstrap)",
                    zorder=1)
    ax.plot(grid, np.exp(intercept + slope * grid), color="black", linestyle="--", linewidth=2,
            label=f"OLS fit: {100 * slope:+.2f}% per +1 pp", zorder=2)

    ax.set_yscale("log")
    ax.yaxis.set_major_locator(LogLocator(base=10, subs=(0.5, 0.6, 0.7, 0.8, 1.0, 1.2)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v / 1000:.0f}k"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("Employees exposed to robots (% of manufacturing employees)")
    ax.set_ylabel("Real avg. annual pay (2021 US$, log)")
    ax.set_title("Real manufacturing wages vs robot exposure, US states 2018–2021", fontsize=13)
    ax.legend(title="Year", loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=10, title_fontsize=10)
    ax.text(0.01, -0.17, f"N = {len(d)} state-years. Simple pooled fit without controls (model M0); "
            "the main model M1 adds controls.", transform=ax.transAxes, fontsize=9, color="0.3")
    return fig


# ----------------------------------------------------------------------------- figure 2


def fig_bootstrap_distribution(bench: pd.DataFrame) -> plt.Figure:
    """Box plot of the bootstrap distribution of beta_1 (in % per pp) for M0 and M1."""
    d = bench[(bench["status"] == "ok")].copy()
    d["pct"] = 100 * d["coef_robot"]
    labels = {"M0": "M0: baseline\n(no controls)", "M1": "M1: main model\n(controls + year effects)"}
    order = [m for m in ("M0", "M1") if m in set(d["model"])]
    fig, ax = plt.subplots(figsize=(7.5, 5.2))

    data = [d.loc[d["model"] == m, "pct"].to_numpy() for m in order]
    bp = ax.boxplot(data, positions=range(len(order)), widths=0.5, patch_artist=True, showfliers=True,
                    flierprops={"marker": "x", "markersize": 4, "markeredgecolor": "0.4", "alpha": 0.6},
                    medianprops={"color": "black", "linewidth": 2})
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(PALETTE[i])
        patch.set_alpha(0.55)
        patch.set_hatch(["//", ".."][i])
        patch.set_edgecolor("black")

    # median with its 95% percentile-bootstrap CI, drawn next to each box
    for i, v in enumerate(data):
        med, lo, hi = np.median(v), np.percentile(v, 2.5), np.percentile(v, 97.5)
        ax.errorbar(i + 0.38, med, yerr=[[med - lo], [hi - med]], fmt=MARKERS[i], color="black",
                    markerfacecolor=PALETTE[i], markersize=8, capsize=6, elinewidth=1.5,
                    label="Median and 95% CI" if i == 0 else None)
        ax.annotate(f"median {med:.2f}\n95% CI\n[{lo:.2f}, {hi:.2f}]", (i + 0.38, lo), xytext=(0, -8),
                    textcoords="offset points", fontsize=10, ha="center", va="top")

    ax.axhline(0, color="#c0392b", linestyle="--", linewidth=1.5, label="No effect (H0: β₁ = 0)")
    ax.set_xticks(range(len(order)), [labels[m] for m in order])
    ax.set_xlim(-0.5, len(order) - 0.15)
    ax.set_ylabel("Effect on real wage (% per +1 pp)")
    ax.set_title(f"Bootstrap distribution of β₁ ({len(data[0])} replicates per model)", fontsize=13)
    ax.legend(loc="upper right", fontsize=10)
    ax.text(0.01, -0.2, "Box: p25–p75; whiskers: 1.5×IQR; ×: replicates outside the whiskers. "
            "States resampled with replacement, seed 42.", transform=ax.transAxes, fontsize=9, color="0.3")
    return fig


# ----------------------------------------------------------------------------- figure 3


def fig_coefficients(table: pd.DataFrame) -> plt.Figure:
    """beta_1 (% per pp) with cluster-robust 95% CI for every estimated model."""
    names = {
        "M0": "M0 baseline (no controls)",
        "M1": "M1 main model",
        "R1": "R1 demeaned exposure",
        "R2": "R2 without flagged cells",
        "R3": "R3 + state fixed effects",
    }
    t = table[table["status"] == "ok"].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    ypos = np.arange(len(t))[::-1]
    for y, (_, r), i in zip(ypos, t.iterrows(), range(len(t))):
        est, lo, hi = 100 * r["coef"], 100 * r["ci_low"], 100 * r["ci_high"]
        main = r["model"] == "M1"
        ax.errorbar(est, y, xerr=[[est - lo], [hi - est]], fmt=MARKERS[i % len(MARKERS)], color=PALETTE[i],
                    markeredgecolor="black", markersize=10 if main else 8, capsize=5,
                    elinewidth=2.5 if main else 1.5, linestyle="none")
        ax.annotate(f"{est:+.2f}%  [{lo:+.2f}, {hi:+.2f}]   p = {r['p_value']:.3f}", (1.02, y),
                    xycoords=("axes fraction", "data"), va="center", fontsize=10)
    ax.axvline(0, color="#c0392b", linestyle="--", linewidth=1.5, label="No effect (β₁ = 0)")
    ax.set_yticks(ypos, [names.get(m, m) for m in t["model"]])
    ax.set_xlabel("Effect on real wage (% per +1 pp of robot exposure), 95% CI")
    ax.set_title("Estimated effect across model specifications", fontsize=13)
    lim = max(abs(100 * t["ci_low"]).max(), abs(100 * t["ci_high"]).max()) * 1.45
    ax.set_xlim(-lim, lim * 0.5)
    ax.legend(loc="lower left", fontsize=10)
    ax.text(0.01, -0.22, "Error bars: 95% confidence intervals with standard errors clustered by state.",
            transform=ax.transAxes, fontsize=9, color="0.3")
    return fig


# ----------------------------------------------------------------------------- entry point


def make_all(cfg: dict, panel: pd.DataFrame, bench: pd.DataFrame, out_dir: Path) -> list[Path]:
    set_style()
    seed = int(cfg["project"]["random_seed"])
    np.random.seed(seed)
    table, _ = run_models(panel, cfg)
    paths = []
    paths += save(fig_wage_vs_exposure(panel, seed=seed), out_dir, "fig1_latency_vs_load")
    paths += save(fig_bootstrap_distribution(bench), out_dir, "fig2_distribution_boxplot")
    paths += save(fig_coefficients(table), out_dir, "fig3_coefficients")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate publication-ready figures")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--panel", default="data/processed/panel.csv")
    parser.add_argument("--bench", default="data/processed/benchmark_clean.csv")
    parser.add_argument("--out-dir", default="reports/figures")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    panel = pd.read_csv(resolve(cfg, args.panel))
    bench = pd.read_csv(resolve(cfg, args.bench))
    for p in make_all(cfg, panel, bench, resolve(cfg, args.out_dir)):
        print(f"saved {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
