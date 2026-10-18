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

> Status: work in progress. Final README (Person A) yahan aayega: prerequisites, `docker compose up`,
> DAG trigger karne ka tareeqa, output kahan milta hai, design decisions, cleaning rules, known limitations.

## Folders

| Folder | Kya hai | Kis ka |
|---|---|---|
| `dags/` | Airflow DAG (`.py`) | A |
| `src/clean/` | Python cleaning code | B |
| `sql/` | Schema, dimensions, fact, quality checks, metric views | C |
| `bi/` | Power BI `.pbix` aur dashboard PDF | D |
| `docs/` | Playbook, README assets, DQ report, insights, star schema diagram | sab |
| `data/` | 9 raw CSVs (git mein nahi, apne computer par rakho) | sab |
| `out/` | Cleaning ka output (generated, git mein nahi) | auto |

Poori team ka plan: `docs/TEAM_PLAYBOOK.md`. Git ke qaayde: `CONTRIBUTING.md`.

## Cleaning ko ek baar chalana (Docker ke baghair)

```powershell
pip install pandas numpy
python src/clean/clean_all.py data out
```
`out/dq_log.csv` mein har fix ke before/after counts, aur `out/reject.csv` mein reason code ke saath reject rows milti hain.
