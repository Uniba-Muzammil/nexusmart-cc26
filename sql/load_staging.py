"""out/ ki clean CSVs ko Postgres ke staging schema mein load karta hai (har run par replace = idempotent).
Sab columns TEXT, taake koi value load ke waqt na toote. Types SQL scripts (04, 05) mein cast hote hain.
Usage (repo root se):  python sql/load_staging.py out
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
TABLES = ["locations", "sellers", "products", "customers", "customer_map", "product_map",
          "orders", "order_items", "payments", "shipping", "returns"]
with conn, conn.cursor() as cur:
    cur.execute("CREATE SCHEMA IF NOT EXISTS staging")
    for t in TABLES:
        path = out / f"{t}.csv"
        if not path.exists():
            print(f"{t}.csv nahi mili, skip"); continue
        with open(path, newline="", encoding="utf-8") as f:
            cols = next(csv.reader(f))
        cur.execute(f"DROP TABLE IF EXISTS staging.{t}")
        cur.execute(f"CREATE TABLE staging.{t} (" + ", ".join(f'"{c}" TEXT' for c in cols) + ")")
        with open(path, encoding="utf-8") as f:
            cur.copy_expert(f"COPY staging.{t} FROM STDIN WITH (FORMAT csv, HEADER true)", f)
        cur.execute(f"SELECT COUNT(*) FROM staging.{t}")
        print(f"staging.{t}: {cur.fetchone()[0]} rows")
