"""Load out/*.csv into Postgres using the type contract (src/clean/clean_schema.py).

  python tools/load_postgres.py out "postgresql://user:pass@host:5432/dbname"      # reload everything (truncate + COPY)
Needs: pip install psycopg2-binary.  Idempotent: running twice gives the same row counts.
Person A can call load(out_dir, dsn) from an Airflow task instead of using the command line.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "clean"))
import clean_schema as CS  # noqa: E402

AUDIT_DDL = """
CREATE SCHEMA IF NOT EXISTS audit;
CREATE TABLE IF NOT EXISTS audit.dq_log (
    step INTEGER, "table" TEXT, issue TEXT, "column" TEXT, before_count BIGINT, after_count BIGINT,
    action TEXT, assumption TEXT);
CREATE TABLE IF NOT EXISTS audit.reject (
    "table" TEXT, record_key TEXT, reason_code TEXT, detail TEXT, raw_row TEXT);
"""


def load(out_dir, dsn):
    import psycopg2
    problems = CS.check(out_dir)
    hard = [p for p in problems if "orphan rows" not in p]
    if hard:
        raise SystemExit("contract check failed, nothing loaded:\n  " + "\n  ".join(hard))
    con = psycopg2.connect(dsn)
    try:
        with con, con.cursor() as cur:                       # one transaction: all or nothing
            cur.execute(CS.ddl("clean") + AUDIT_DDL)
            for t in CS.LOAD_ORDER:
                cur.execute(f"TRUNCATE clean.{t}")
                with open(os.path.join(out_dir, f"{t}.csv"), encoding="utf-8") as f:
                    cur.copy_expert(f"COPY clean.{t} ({', '.join(CS.columns(t))}) FROM STDIN WITH (FORMAT csv, HEADER true)", f)
            for t, cols in [("dq_log", "step,\"table\",issue,\"column\",before_count,after_count,action,assumption"),
                            ("reject", "\"table\",record_key,reason_code,detail,raw_row")]:
                cur.execute(f"TRUNCATE audit.{t}")
                with open(os.path.join(out_dir, f"{t}.csv"), encoding="utf-8") as f:
                    cur.copy_expert(f"COPY audit.{t} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)", f)
            counts = {}
            for t in CS.LOAD_ORDER:
                cur.execute(f"SELECT count(*) FROM clean.{t}")
                counts[t] = cur.fetchone()[0]
        return counts
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    for t, n in load(sys.argv[1], sys.argv[2]).items():
        print(f"[load] clean.{t:13s} {n:>8} rows")
