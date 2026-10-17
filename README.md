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
