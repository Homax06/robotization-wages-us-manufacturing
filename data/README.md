# Data

```
data/
├── sample/   tiny files for the smoke test (committed)
└── raw/      full downloaded data (NOT committed, see .gitignore)
```

## Files expected in `data/raw/` for a full run (`data.mode: full`)

| Path | What it is | Where to get it |
|---|---|---|
| `data/raw/ASM Robotics.xlsx` | US Census Bureau, Annual Survey of Manufactures, industrial robotic equipment 2018-2021. Sheets used: `Percent of... Geo` and `Percent of... Geo demean`. | https://www2.census.gov/programs-surveys/asm/tables/2024/ASM%20Robotics.xlsx (page: https://www.census.gov/library/publications/2024/econ/2021-asm-robotic-equipment.html) |
| `data/raw/qcew/*.csv` | BLS QCEW annual-average CSV files for 2018-2021, any number of files. Needed columns: `area_fips`, `own_code`, `industry_code`, `year`, `annual_avg_estabs`, `annual_avg_emplvl`, `avg_annual_pay`. The pipeline keeps private ownership (`own_code = 5`), industry `31-33`, state-level areas. | https://www.bls.gov/cew/downloadable-data-files.htm (column layout: https://www.bls.gov/cew/about-data/downloadable-file-layouts/annual/naics-based-annual-layout.htm) |
| `data/raw/cpi_u_annual.csv` | Two columns, `year,cpi_u`: CPI-U (all items, US city average) annual averages. | https://www.bls.gov/cpi/ |

Raw data are public statistics, but they are large or binary, so they are kept out of Git.
Record the download date of every file in `config.yaml` (`data.full.downloaded_on`).

Last reviewed by Aruna Zhakipova.
