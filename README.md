# NexusMart Data Analytics Pipeline (CODE//CONNECT'26) 
clone the repo https://github.com/Uniba-Muzammil/nexusmart-cc26.git
git checkout main
git pull origin main

# PART A (DATA CLEANING)
## Where to put the data (not pushed to repo because they are confidential)
After cloning, you will see an empty `data/` folder (it contains only a `.gitkeep` placeholder so that Git keeps the folder). Download or copy the 9 raw CSV files and readme data file (basically the zip file provided by the module lead) into `data/`: customers, products, sellers, locations, orders, order_items, payments, shipping, returns
# THEN 
pip install -r requirements-clean.txt
# Check 1 :
python src/clean/clean_all.py data out
# Check 2: Type contract
python src/clean/clean_schema.py check out
# Check 3: Headline numbers
python src/clean/sensitivity.py data out

# PART B (PIPELINE)

# Create .env
Run this in terminal "copy .env.example .env " OR you can directly create a env file in the project root, than use the .env.example file to add data in env you can use the same example data will be helpful or you can have your username and password accept for the WH_PW that should be same.

# Start Docker
docker compose up airflow-init
docker compose up -d

# Run the pipeline
Open http://localhost:8080 and log in with AIRFLOW_ADMIN_USER / AIRFLOW_ADMIN_PW from your .env. Find nexusmart_analytics_pipeline, press ▶ and choose Trigger DAG.














# NexusMart Data Analytics Pipeline (CODE//CONNECT'26)

Raw CSVs → Python cleaning → PostgreSQL star schema → quality checks → KPI views → Power BI.
Everything runs as one Airflow DAG inside Docker, so it behaves the same on any computer.

## What you need

- Docker Desktop (Windows: WSL2 enabled), running
- Git
- The 9 competition CSVs (they are not in this repo)

## Run it (5 steps)

**1. Get the code**
```bash
git clone https://github.com/Uniba-Muzammil/nexusmart-cc26.git
cd nexusmart-cc26
```

**2. Put the raw data in `data/`**

Create a folder `data` and copy the 9 CSVs into it:
`customers.csv, products.csv, sellers.csv, locations.csv, orders.csv, order_items.csv, payments.csv, shipping.csv, returns.csv`

**3. Create your `.env`** (passwords live here only, never in code)
```bash
cp .env.example .env          # Windows PowerShell: copy .env.example .env
```
Open `.env` and replace every `change_me...` value with your own.

**4. Start Docker** (first time takes a few minutes to build the image)
```bash
docker compose up airflow-init
docker compose up -d
```

**5. Run the pipeline**

Open http://localhost:8080, log in with `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PW` from your `.env`,
find `nexusmart_analytics_pipeline` and press ▶ (Trigger DAG). Or from the terminal:
```bash
docker compose exec airflow-scheduler airflow dags trigger nexusmart_analytics_pipeline
```
All 10 tasks turn green in a few minutes. Running it again is safe and gives the same result.

Stop everything: `docker compose down` (add `-v` to also delete the database volumes).

## What the pipeline does

```
extract → validate_raw → clean → check_contract → load_staging
        → build_dimensions → build_fact → quality_checks → publish_metrics → verify_cleaned_data_unchanged
```

| Task | What it does | Code |
|---|---|---|
| `extract` | finds the 9 raw CSVs and logs rows read | `dags/nexusmart_dag.py` |
| `validate_raw` | stops the run if a file or a required column is missing | `src/clean/clean_all.py` |
| `clean` | all cleaning in Python, writes `out/*.csv`, `dq_log.csv`, `reject.csv`; fails if a table rejects more than its limit | `src/clean/` |
| `check_contract` | every clean table has the agreed columns, types and unique keys | `src/clean/clean_schema.py` |
| `load_staging` | loads `out/` into Postgres schemas `clean` and `audit` (tables replaced on every run, so reruns never duplicate) | `sql/load_staging.py` |
| `build_dimensions` | schema `mart`, DimDate (with Ramadan / Eid / 14 Aug / 11.11 / Black Friday flags) and 4 dimensions, each with an Unknown (-1) row | `sql/01_schemas.sql`, `sql/02_dims.sql` |
| `build_fact` | FactSales, one row per order line, plus the RFM segment on DimCustomer | `sql/03_fact.sql` |
| `quality_checks` | row counts, no duplicate keys, no NULL or missing keys, net amount, shipping fee and returns reconcile; the run fails if any check fails | `sql/04_checks.sql` |
| `publish_metrics` | KPI views for Power BI and logs the headline KPIs | `sql/05_metrics.sql` |
| `verify_cleaned_data_unchanged` | checks (sha256) that no cleaned file changed after the `clean` task | `dags/nexusmart_dag.py` |

Each task logs records **read / rejected / loaded** (Airflow UI → task → Logs).

## Where the results are

| Output | Location |
|---|---|
| Cleaned tables | `out/*.csv` on your computer, and schema `clean` in Postgres |
| Data quality log and rejected rows (with reason codes) | `out/dq_log.csv`, `out/reject.csv`, schema `audit` |
| Star schema for Power BI | schema `mart`: `fact_sales`, `dim_date`, `dim_customer`, `dim_product`, `dim_seller`, `dim_location` (diagram: `docs/star_schema.png`) |
| KPI views | `mart.v_kpi_overall`, `mart.v_kpi_monthly`, `mart.v_rfm_segments`, `mart.v_unknown_member_counts` |

Connect Power BI (or psql) to the warehouse: server `localhost:5433`, database `wh`, user `wh`, password = `WH_PW` from `.env`.

## How cleaned data is protected

The `clean` task never overwrites cleaned files by accident. It is controlled by `NX_CLEAN_MODE` in `.env`:

| Mode | Behaviour |
|---|---|
| `auto` (default) | `out/` empty (fresh clone) → clean the raw data and write `out/`. `out/` already filled → reuse those files read-only. Stops without changing anything if `out/` is only partly filled, or if a raw CSV is newer than the cleaned files. |
| `reuse` | always use the existing `out/` files, never re-clean |
| `force` | re-clean; if the result differs, the old files are first copied to `out/_backup/<date_time>/`, then replaced |

Cleaning always runs in a temporary folder first, so a failed quality gate never leaves half-written files.
The raw `data/` folder is mounted read-only into Docker, so the pipeline cannot change it.
After changing `.env`, restart with `docker compose up -d`.

## Design decisions

- **All cleaning is Python code.** No manual edits in Excel, the database or Power Query. Every fix is counted in `dq_log.csv`; every dropped record is in `reject.csv` with a reason code.
- **Idempotent.** Cleaning gives byte-identical output on rerun; loads are truncate-and-load in one transaction; SQL scripts rebuild their tables.
- **Fail loudly.** Missing columns, a quality gate breach, a contract violation or a failed SQL check stops the run instead of loading bad data.
- **FactSales grain = order line.** Returns are aggregated per line (valid returns only), the order shipping fee is split across lines by gross amount, one payment row per order, and unknown customers/products/sellers/cities map to an Unknown (-1) row instead of being deleted.
- **Secrets only in `.env`** (not committed).

Cleaning rules and key assumptions: `src/clean/README_CLEANING.md`. Data quality report: `docs/data_quality_report.pdf`.

## Known limitations

- The DimDate calendar covers 2024-01-01 to 2025-12-31 (the brief's period plus room for late returns).
- New label spellings in a new data drop are mapped fuzzily or to `Unknown` and listed in `dq_log.csv` (`UNMATCHED LABELS`); the right category must then be added to `src/clean/nx_config.py`.
- `sensitivity.py` and `make_dq_report.py` (the data quality report PDF) are run by hand, not by the DAG, because they write into `out/` and `docs/`.

## Folders

| Folder | Contents |
|---|---|
| `dags/` | Airflow DAG |
| `src/clean/` | Python cleaning code |
| `sql/` | schema, dimensions, fact, quality checks, metric views |
| `tools/` | Postgres loader, stress test |
| `bi/` | Power BI `.pbix` and dashboard PDF |
| `docs/` | team playbook, data quality report, handoff guide |
| `data/` | the 9 raw CSVs (not in git) |
| `out/` | cleaned output (not in git) |
| `out_samples/` | small samples of `dq_log`, `reject`, `sensitivity` |

## Run the cleaning alone (without Docker)

```bash
pip install -r requirements-clean.txt
python src/clean/clean_all.py data out
```
Note: this writes straight into `out/` (no `NX_CLEAN_MODE` protection). Use a different folder, e.g. `python src/clean/clean_all.py data out_test`, if `out/` already holds cleaned data you want to keep.

Team plan: `docs/TEAM_PLAYBOOK.md`. Git rules: `CONTRIBUTING.md`.
