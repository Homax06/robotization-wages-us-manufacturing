# Sample data (pipeline smoke test only)

These micro-files let a reviewer run the whole pipeline in seconds.
**They are not used for any research conclusion.**

| File | Rows | Origin |
|---|---|---|
| `robots_sample.csv` | 10 | Real cells copied from the US Census Bureau ASM robotics table ("Percent of... Geo" and "...Geo demean" sheets), 5 states x 2 years. Values are kept as the raw text found in the table (fractions, `32.5%(s)`, `D`, ...) so that the same cell parser is exercised as in a full run. |
| `qcew_sample.csv` | 10 | **SYNTHETIC** wage, employment and establishment numbers (column `is_synthetic = 1`). They only mimic the layout of the BLS QCEW annual files. |
| `cpi_sample.csv` | 4 | CPI-U annual averages (1982-84 = 100). Re-check against BLS before using them in the full run. |

The full data are described in [`../README.md`](../README.md) and downloaded by the authors in Week 7.
