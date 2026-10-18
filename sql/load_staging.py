"""LOCAL helper (apne laptop par warehouse test karne ke liye). Airflow DAG ka load_staging task yehi kaam production mein karta hai.
out/ ki clean CSVs ko Postgres mein load karta hai: clean.* aur audit.dq_log / audit.reject (har run par replace = idempotent).
Sab columns TEXT (SQL scripts khud cast karti hain). Usage (repo root se):  python sql/load_staging.py out
Password .env ki WH_PW se (ya environment variable), code mein nahi."""
import csv, os, sys
from pathlib import Path
import psycopg2

out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")

def pw():
    if os.environ.get("WH_PW"):
        return os.environ["WH_PW"]
    env = Path(".env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("WH_PW="):
                return line.split("=", 1)[1].strip()
    sys.exit("WH_PW nahi mila (.env ya environment variable)")

conn = psycopg2.connect(host=os.environ.get("WH_HOST", "localhost"), port=os.environ.get("WH_PORT", "5433"),
                        dbname="wh", user="wh", password=pw())
PLAN = [("clean", t) for t in ["locations", "sellers", "products", "customers", "customer_map", "product_map",
                               "orders", "order_items", "payments", "shipping", "returns"]] + \
       [("audit", t) for t in ["dq_log", "reject"]]
with conn, conn.cursor() as cur:
    for schema in ("raw", "clean", "audit", "mart"):
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for schema, t in PLAN:
        path = out / f"{t}.csv"
        if not path.exists():
            print(f"{t}.csv nahi mili, skip"); continue
        with open(path, newline="", encoding="utf-8") as f:
            cols = next(csv.reader(f))
        cur.execute(f"DROP TABLE IF EXISTS {schema}.{t}")
        cur.execute(f"CREATE TABLE {schema}.{t} (" + ", ".join(f'"{c}" TEXT' for c in cols) + ")")
        with open(path, encoding="utf-8") as f:
            cur.copy_expert(f"COPY {schema}.{t} FROM STDIN WITH (FORMAT csv, HEADER true)", f)
        cur.execute(f"SELECT COUNT(*) FROM {schema}.{t}")
        print(f"{schema}.{t}: {cur.fetchone()[0]} rows")
        cur.execute(f"ANALYZE {schema}.{t}")   # planner ko statistics do, warna fact load bahut slow ho sakta hai
