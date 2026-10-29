# Robotization and Wages in the US Manufacturing Industry

**Authors:** Nursultan Abukhanov ([@Homax06](https://github.com/Homax06)) · Aruna Zhakipova ([@zhakipovaaruna125-cpu](https://github.com/zhakipovaaruna125-cpu))

Course project, *Research Methods*. The full study design is in the [Methodology Passport Card](docs/Methodology_Card.pdf); the formal model is in [docs/domain_model.md](docs/domain_model.md).

## Overview

**Research question.** Is a higher share of manufacturing employees exposed to industrial robots in a US state associated with a different level of real wages in that state's manufacturing sector?

**Design.** Quantitative observational study on a state × year panel, 2018–2021, NAICS 31–33 (manufacturing), private ownership.

| | |
|---|---|
| Exposure (X) | Percent of employees exposed to robots, by state (Census Bureau, Annual Survey of Manufactures, ASM) |
| Outcome (Y) | ln(real average annual pay), by state (BLS QCEW; deflated with CPI-U, base year 2021) |
| Controls | ln(employment), ln(establishments), year effects |
| Estimator | OLS, standard errors clustered by state; cluster bootstrap (1,000 replicates) for 95% CI |
| Hypotheses | H0: β₁ = 0 · H1: β₁ ≠ 0 (two-sided, α = 0.05) |

The coefficient β₁ × 100 is read as the percent change in real wages per +1 percentage point of robot exposure. The result is an **association**, not proof of causation (see the card, section on limitations).

## Results & Discussion

<!-- TODO: replace every TODO value with the numbers from data/processed/metrics_summary.csv
     and results/results_table.csv after the full-data run. -->

### Descriptive statistics (state × year panel, N = TODO)

| Variable | Mean ± SD | Median (p25–p75) |
|---|---|---|
| Robot exposure, % of employees | TODO ± TODO | TODO (TODO–TODO) |
| Real average annual pay, 2021 US$ | TODO ± TODO | TODO (TODO–TODO) |
| Employment, thousands | TODO ± TODO | TODO (TODO–TODO) |

### Main result: Baseline (M0) vs Main model (M1)

| Model | β₁ (robot exposure) | % change in real wage per +1 pp | Cluster-robust 95% CI | Bootstrap 95% CI | p-value | Adj. R² | Bootstrap error rate |
|---|---|---|---|---|---|---|---|
| M0, no controls (baseline) | TODO | TODO | [TODO, TODO] | [TODO, TODO] | TODO | TODO | TODO |
| **M1, controls + year effects** | **TODO** | **TODO** | **[TODO, TODO]** | **[TODO, TODO]** | **TODO** | **TODO** | **TODO** |

Bootstrap: 1,000 replicates after 20 warm-up replicates, states resampled with replacement, seed 42.
Bootstrap distribution of β₁ reported as Median (p25–p75): M0 TODO (TODO–TODO), M1 TODO (TODO–TODO).

### Robustness checks

| Model | Change vs M1 | β₁ | 95% CI | Same sign as M1? |
|---|---|---|---|---|
| R1 | demeaned (industry-composition-adjusted) exposure | TODO | [TODO, TODO] | TODO |
| R2 | cells flagged "(s)" removed | TODO | [TODO, TODO] | TODO |
| R3 | state fixed effects added | TODO | [TODO, TODO] | TODO |

### Guardrails

| Check | Value | Criterion | Status |
|---|---|---|---|
| VIF (max) | TODO | < 10 | TODO |
| Breusch–Pagan p-value | TODO | > 0.05 (clustered SE used anyway) | TODO |
| Jarque–Bera p-value | TODO | > 0.05 | TODO |
| Min states per year | TODO | ≥ 45 | TODO |
| Share of withheld robot cells | TODO | ≤ 10% | TODO |
| Bootstrap error rate (M1) | TODO | ≤ 5% | TODO |
| Two runs identical | TODO | identical | TODO |

### Figures

![Figure 1. Real wage vs robot exposure](reports/figures/fig1_latency_vs_load.png)

**Figure 1.** Real average annual pay (2021 US$, log scale) against the share of employees exposed to robots, by state and year. Line: OLS fit with 95% confidence band.

![Figure 2. Bootstrap distribution of the robot coefficient](reports/figures/fig2_distribution_boxplot.png)

**Figure 2.** Distribution of β₁ over 1,000 cluster-bootstrap replicates for M0 and M1. Dashed line: β₁ = 0.

Vector versions (PDF) are in [reports/figures/](reports/figures/).

### Discussion

<!-- TODO: 4–6 sentences in plain English, written after the results are known:
     1. The answer to the research question (reject / fail to reject H0 in M1, with β₁ and CI).
     2. What the number means in practice (percent change in wages per +1 pp of exposure).
     3. How M1 differs from the baseline M0 and why (role of the controls).
     4. Whether R1–R3 confirm the result.
     5. Main limitations: association not causation, short panel (4 years), Census suppression. -->

TODO

## Domain model

The regression equation, OLS loss function, metrics and notation table are in [docs/domain_model.md](docs/domain_model.md).

## Repository structure

```
.
├── README.md
├── LICENSE                     MIT
├── config.yaml                 all parameters: years, sector, paths, model, guardrails, bootstrap, seed
├── requirements.txt            exact package versions (Python 3.13)
├── Dockerfile                  reproducible environment
├── pytest.ini
├── src/
│   ├── main.py                 entry point of the regression pipeline: python -m src.main
│   ├── load_data.py            reads/cleans ASM robots, QCEW wages, CPI; builds the panel
│   ├── analysis.py             models M0, M1, R1–R3 and guardrail diagnostics
│   ├── collector.py            cluster bootstrap with warm-up, JSONL logging, error tracking
│   ├── process_data.py         cleaning and statistical aggregation of the bootstrap log
│   ├── visualize.py            publication-ready figures
│   ├── config.py               config loading, SHA-256 hashing of inputs
│   └── states.py               state names ↔ FIPS codes
├── tests/                      unit/integration tests
├── data/
│   ├── sample/                 micro-files (10 rows each) used by the smoke test
│   ├── raw/                    full data NOT in Git, except the bootstrap log:
│   │   ├── test_run.jsonl      one line per replicate and model (warm-up and benchmark)
│   │   └── test_run_meta.json  hardware, software, seed and input hashes of the run
│   └── processed/
│       └── metrics_summary.csv cleaned and aggregated metrics
├── notebooks/
│   └── 01_data_analysis.ipynb  full analysis, executed top to bottom
├── reports/figures/            fig1, fig2 as .pdf (vector) and .png (300 DPI)
├── results/                    regression outputs (not in Git)
└── docs/
    ├── Methodology_Card.pdf
    └── domain_model.md
```

## System requirements

- Python **3.13** (or Docker)
- ~500 MB disk for packages; no GPU
- Internet only to install packages or to download the full data

## Quickstart

Option A, Docker (nothing else to install):

```bash
docker build -t robots-wages .
docker run --rm -v "$(pwd)/results:/app/results" robots-wages
```

Option B, plain Python:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest                                      # tests
```

### Full data run

1. Download the files listed in [data/README.md](data/README.md) into `data/raw/` and fill in `downloaded_on` in `config.yaml`.
2. Run the pipeline in this order:

```bash
python -m src.main --config config.yaml --mode full        # regression models + guardrails -> results/
python -m src.collector --config config.yaml --mode full   # bootstrap log -> data/raw/test_run.jsonl
python -m src.process_data                                 # -> data/processed/metrics_summary.csv
python -m src.visualize                                    # -> reports/figures/
```

3. Or open `notebooks/01_data_analysis.ipynb` and run *Kernel → Restart & Run All*.

Without `--mode full` every command runs on the synthetic sample (smoke test only; the numbers mean nothing).

## Reproducibility

Fixed seed (42) in `config.yaml` for the bootstrap; exact package pins; the log and `test_run_meta.json` record Python/package versions, CPU, RAM, OS and SHA-256 of every input file; the regression pipeline computes everything twice and checks that the result tables are identical.

## Data sources

- U.S. Census Bureau, Annual Survey of Manufactures: Robotic Equipment tables (experimental data product).
- U.S. Bureau of Labor Statistics, Quarterly Census of Employment and Wages (QCEW), annual averages.
- U.S. Bureau of Labor Statistics, Consumer Price Index for All Urban Consumers (CPI-U).

## Citation

```bibtex
@misc{abukhanov_zhakipova_2026_robotization,
  author = {Abukhanov, Nursultan and Zhakipova, Aruna},
  title  = {Robotization and Wages in the {US} Manufacturing Industry},
  year   = {2026},
  howpublished = {\url{https://github.com/Homax06/robotization-wages-us-manufacturing}},
  note   = {Course project, Research Methods}
}
```

## License

[MIT](LICENSE) © 2026 Nursultan Abukhanov and Aruna Zhakipova
