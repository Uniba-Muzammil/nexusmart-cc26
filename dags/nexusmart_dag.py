"""NexusMart analytics pipeline (CODE//CONNECT'26, Person A).

One DAG, run manually (schedule=None). Tasks run in this order:

    extract -> validate_raw -> clean -> check_contract -> load_staging
            -> build_dimensions -> build_fact -> quality_checks -> publish_metrics
            -> verify_cleaned_data_unchanged

| Task                          | What it does                                                                  |
|-------------------------------|-------------------------------------------------------------------------------|
| extract                       | finds the 9 raw CSVs in data/ and logs their row counts                       |
| validate_raw                  | required columns present, no empty file (src/clean/clean_all.validate_raw)    |
| clean                         | Python cleaning (src/clean/clean_all.run) -> out/*.csv + dq_log + reject      |
| check_contract                | column/type/PK contract of the clean CSVs (src/clean/clean_schema.check)      |
| load_staging                  | out/ -> Postgres schemas `clean` + `audit` (sql/load_staging.py)              |
| build_dimensions              | sql/01_schemas + sql/02_dims: schema `mart`, DimDate + 4 dims (Unknown = -1)  |
| build_fact                    | sql/03_fact: FactSales (grain = order line) + RFM segment on DimCustomer      |
| quality_checks                | sql/04_checks: one row per check, task fails if any check has failed_rows > 0 |
| publish_metrics               | sql/05_metrics: KPI views for Power BI, logs the headline KPIs                |
| verify_cleaned_data_unchanged | sha256 of every out/*.csv must equal the value recorded after `clean`         |

Every task logs records read / rejected / loaded where it applies.

Cleaned data protection (out/ is never overwritten by accident)
---------------------------------------------------------------
Environment variable NX_CLEAN_MODE controls the `clean` task:
  auto  (default) out/ already holds the cleaned files -> reuse them read-only.
                  out/ holds none of them (fresh clone) -> clean into a temp folder,
                  pass the quality gate, then copy into out/.
                  Fails (writes nothing) if out/ is only partly filled, or if a raw
                  CSV is newer than the cleaned files (new data drop: use force).
  reuse           always reuse the existing out/ files, never run cleaning.
  force           re-clean into a temp folder; if the result differs from out/, the old
                  files are first copied to out/_backup/<timestamp>/ and then replaced.
In every mode cleaning writes to a temp folder first, so a failed quality gate never
leaves half-written files in out/.

Credentials come only from environment variables (.env via docker compose), never code.
"""
import csv
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG  # type: ignore
from airflow.exceptions import AirflowException  # type: ignore
from airflow.operators.python import PythonOperator  # type: ignore

log = logging.getLogger(__name__)

# ------------------------------------------------------------------ paths
# Inside docker compose the repo folders are mounted under /opt/airflow (dags/, src/, sql/, tools/, data/, out/).
REPO = Path(os.environ.get("NX_REPO_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = Path(os.environ.get("DATA_DIR", REPO / "data"))
OUT_DIR = Path(os.environ.get("OUT_DIR", REPO / "out"))
SQL_DIR = REPO / "sql"
for _p in (REPO / "src" / "clean", REPO / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RAW_FILES = ["customers", "products", "sellers", "locations", "orders", "order_items",
             "payments", "shipping", "returns"]
CLEAN_TABLES = ["customers", "customer_map", "products", "product_map", "sellers", "locations",
                "orders", "order_items", "payments", "shipping", "returns"]
AUDIT_FILES = ["dq_log", "reject"]
CLEANED_FILES = CLEAN_TABLES + AUDIT_FILES          # what clean_all.run writes to out/
CLEAN_MODES = ("auto", "reuse", "force")


# ------------------------------------------------------------------ helpers
def _csv_rows(path):
    """Data rows in a CSV (header excluded). csv module, so quoted newlines are counted correctly."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return max(sum(1 for _ in csv.reader(f)) - 1, 0)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fingerprint(folder):
    """sha256 of every top-level CSV in out/ (covers sensitivity.csv or anything else kept there too)."""
    folder = Path(folder)
    if not folder.is_dir():
        return {}
    return {p.name: _sha256(p) for p in sorted(folder.glob("*.csv")) if p.is_file()}


def _log_table(title, rows, header):
    log.info(title)
    log.info("  " + " | ".join(f"{h:>14}" for h in header))
    for r in rows:
        log.info("  " + " | ".join(f"{str(v):>14}" for v in r))


def _summary_from_audit(out_dir):
    """read / rejected / loaded per raw table, taken from the TABLE SUMMARY rows of dq_log.csv and reject.csv.
    Used when the cleaned files are reused, so nothing has to be recomputed (or rewritten)."""
    summary = {}
    with open(Path(out_dir) / "dq_log.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("issue") == "TABLE SUMMARY":
                summary[row["table"]] = {"rows_read": int(float(row["before_count"])),
                                         "rows_rejected": 0,
                                         "rows_loaded": int(float(row["after_count"]))}
    with open(Path(out_dir) / "reject.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("table") in summary:
                summary[row["table"]]["rows_rejected"] += 1
    return summary


def _wh_password():
    pw = os.environ.get("WH_PASSWORD") or os.environ.get("WH_PW")
    if not pw:
        raise AirflowException("Warehouse password not set: put WH_PW in .env (see .env.example)")
    return pw


def _wh_params():
    return {"host": os.environ.get("WH_HOST", "localhost"), "port": os.environ.get("WH_PORT", "5433"),
            "dbname": os.environ.get("WH_DB", "wh"), "user": os.environ.get("WH_USER", "wh"),
            "password": _wh_password()}


def _connect():
    import psycopg2
    conn = psycopg2.connect(**_wh_params())
    conn.autocommit = True          # the SQL files manage their own BEGIN/COMMIT
    return conn


def _run_sql_file(name):
    path = SQL_DIR / name
    log.info("running %s", path)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _split_statements(sql):
    """Split a file of plain SELECT/WITH statements on ';' at line end (used for sql/04_checks.sql)."""
    parts = [p.strip() for p in re.split(r";[ \t]*(?:\r?\n|$)", sql)]
    keep = []
    for p in parts:
        code = "\n".join(line for line in p.splitlines() if not line.strip().startswith("--")).strip()
        if code:
            keep.append(p)
    return keep


# ------------------------------------------------------------------ tasks
def extract(**_):
    """Raw CSVs present and non-empty; log rows read per file."""
    if not DATA_DIR.is_dir():
        raise AirflowException(f"data folder not found: {DATA_DIR} (put the 9 raw CSVs there)")
    counts, missing = {}, []
    for name in RAW_FILES:
        path = DATA_DIR / f"{name}.csv"
        if not path.exists():
            missing.append(path.name)
            continue
        counts[name] = _csv_rows(path)
    if missing:
        raise AirflowException(f"missing raw files in {DATA_DIR}: {missing}")
    empty = [n for n, c in counts.items() if c == 0]
    if empty:
        raise AirflowException(f"raw files with no data rows: {empty}")
    _log_table(f"[extract] raw files in {DATA_DIR}", [(n, c) for n, c in counts.items()], ["file", "rows_read"])
    log.info("[extract] total rows read: %d", sum(counts.values()))
    return counts


def validate_raw(**_):
    import clean_all
    import nx_config
    problems = clean_all.validate_raw(str(DATA_DIR))
    if problems:
        raise AirflowException("raw data validation failed:\n  " + "\n  ".join(problems))
    rows = [(n, _csv_rows(DATA_DIR / f"{n}.csv"), len(cols), 0) for n, cols in nx_config.REQUIRED_COLUMNS.items()]
    _log_table("[validate_raw] all 9 files have the required columns (no rows are dropped here)", rows,
               ["file", "rows_read", "required_cols", "rows_rejected"])


def _check_partial_or_stale(present, missing):
    if missing:
        raise AirflowException(
            f"out/ is only partly filled (missing: {missing}). Nothing was changed. "
            "Restore the missing files, or set NX_CLEAN_MODE=force to re-clean (old files are backed up first).")
    newest_raw = max((DATA_DIR / f"{n}.csv").stat().st_mtime for n in RAW_FILES)
    oldest_clean = min((OUT_DIR / f"{n}.csv").stat().st_mtime for n in present)
    if newest_raw > oldest_clean:
        raise AirflowException(
            "a raw CSV in data/ is newer than the cleaned files in out/ (new data drop?). Nothing was changed. "
            "Set NX_CLEAN_MODE=force to re-clean (old files are backed up first), "
            "or NX_CLEAN_MODE=reuse to keep using the existing cleaned files.")


def _install_cleaned(tmp_dir, mode):
    """Copy freshly cleaned files from tmp_dir into out/. Identical files are left untouched;
    in force mode differing files are backed up before being replaced."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    changed = [n for n in CLEANED_FILES
               if not (OUT_DIR / f"{n}.csv").exists() or _sha256(OUT_DIR / f"{n}.csv") != _sha256(tmp_dir / f"{n}.csv")]
    if not changed:
        log.info("[clean] new output is byte-identical to out/; nothing replaced")
        return
    existing = [n for n in changed if (OUT_DIR / f"{n}.csv").exists()]
    if existing:
        if mode != "force":      # safety net: never reached in auto mode, which only writes into an empty out/
            raise AirflowException(f"refusing to overwrite existing cleaned files {existing} without NX_CLEAN_MODE=force")
        backup = OUT_DIR / "_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup.mkdir(parents=True, exist_ok=False)
        for n in existing:
            shutil.copy2(OUT_DIR / f"{n}.csv", backup / f"{n}.csv")
        log.warning("[clean] force mode: previous versions of %s backed up to %s", existing, backup)
    for n in changed:                       # copy next to the target, then atomic rename
        part = OUT_DIR / f".{n}.csv.part"
        shutil.copy2(tmp_dir / f"{n}.csv", part)
        os.replace(part, OUT_DIR / f"{n}.csv")
    log.info("[clean] wrote %d file(s) to %s: %s", len(changed), OUT_DIR, changed)


def clean(**_):
    mode = os.environ.get("NX_CLEAN_MODE", "auto").strip().lower()
    if mode not in CLEAN_MODES:
        raise AirflowException(f"NX_CLEAN_MODE must be one of {CLEAN_MODES}, got {mode!r}")
    present = [n for n in CLEANED_FILES if (OUT_DIR / f"{n}.csv").exists()]
    missing = [n for n in CLEANED_FILES if n not in present]
    before = _fingerprint(OUT_DIR)

    if mode == "reuse" or (mode == "auto" and present):
        if mode == "auto":
            _check_partial_or_stale(present, missing)
        elif missing:
            raise AirflowException(f"NX_CLEAN_MODE=reuse but out/ is missing {missing}")
        log.info("[clean] mode=%s: existing cleaned files in %s are reused read-only (not regenerated)", mode, OUT_DIR)
        summary = _summary_from_audit(OUT_DIR)
        action = "reused"
    else:
        import clean_all
        with tempfile.TemporaryDirectory(prefix="nx_clean_") as tmp:
            log.info("[clean] mode=%s: cleaning %s into temp folder %s", mode, DATA_DIR, tmp)
            summary = clean_all.run(str(DATA_DIR), tmp)     # raises RuntimeError if the quality gate fails
            _install_cleaned(Path(tmp), mode)
        action = "cleaned"

    _log_table(f"[clean] {action}: records per table (from dq_log TABLE SUMMARY / reject)",
               [(t, s["rows_read"], s["rows_rejected"], s["rows_loaded"]) for t, s in summary.items()],
               ["table", "rows_read", "rows_rejected", "rows_loaded"])
    after = _fingerprint(OUT_DIR)
    if action == "reused" and after != before:
        raise AirflowException("cleaned files changed while being reused; stopping")
    return {"mode": mode, "action": action, "summary": summary, "fingerprint": after}


def check_contract(**_):
    import clean_schema
    problems = clean_schema.check(str(OUT_DIR))
    soft = [p for p in problems if "orphan rows" in p]     # orphans are kept on purpose (flagged, mapped to -1)
    hard = [p for p in problems if p not in soft]
    for p in soft:
        log.warning("[check_contract] expected / soft: %s", p)
    if hard:
        raise AirflowException("clean data contract failed:\n  " + "\n  ".join(hard))
    rows = [(t, _csv_rows(OUT_DIR / f"{t}.csv"), 0) for t in CLEAN_TABLES]
    _log_table(f"[check_contract] {len(CLEAN_TABLES)} tables pass the type contract (columns, types, unique keys)",
               rows, ["table", "rows_checked", "rows_failing"])


def load_staging(**_):
    """out/ -> schemas clean + audit via the warehouse loader sql/load_staging.py (replace on every run = idempotent).
    Reads out/ only; never writes there."""
    params = _wh_params()
    env = dict(os.environ, WH_PW=params["password"], WH_HOST=params["host"], WH_PORT=str(params["port"]))
    res = subprocess.run([sys.executable, str(SQL_DIR / "load_staging.py"), str(OUT_DIR)],
                         cwd=str(REPO), env=env, capture_output=True, text=True)
    for line in (res.stdout + res.stderr).splitlines():
        log.info("[load_staging] %s", line)
    if res.returncode != 0:
        raise AirflowException(f"sql/load_staging.py failed with exit code {res.returncode}")

    # records read (CSV rows in out/) vs loaded (rows now in Postgres); rejected rows stay in audit.reject
    rows = []
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for schema, t in [("clean", t) for t in CLEAN_TABLES] + [("audit", t) for t in AUDIT_FILES]:
                cur.execute(f"SELECT COUNT(*) FROM {schema}.{t}")
                loaded = cur.fetchone()[0]
                read = _csv_rows(OUT_DIR / f"{t}.csv")
                rows.append((f"{schema}.{t}", read, read - loaded, loaded))
    finally:
        conn.close()
    _log_table("[load_staging] records per table", rows, ["table", "rows_read", "rows_rejected", "rows_loaded"])
    bad = [r[0] for r in rows if r[2] != 0]
    if bad:
        raise AirflowException(f"row count mismatch between out/ and Postgres for {bad}")


def build_dimensions(**_):
    for f in ("01_schemas.sql", "02_dims.sql"):
        _run_sql_file(f)
    sources = {"dim_customer": "clean.customers", "dim_product": "clean.products",
               "dim_seller": "clean.sellers", "dim_location": "clean.locations"}
    conn = _connect()
    try:
        with conn.cursor() as cur:
            rows = []
            for t in ("dim_date", "dim_customer", "dim_product", "dim_seller", "dim_location"):
                cur.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE {t.split('_', 1)[1]}_key = -1) FROM mart.{t}")
                loaded, unknown = cur.fetchone()
                if t in sources:
                    cur.execute(f"SELECT COUNT(*) FROM {sources[t]}")
                    read = cur.fetchone()[0]
                    rows.append((t, read, read - (loaded - unknown), loaded))
                else:
                    rows.append((t, "-", 0, loaded))       # generated calendar, not read from a table
    finally:
        conn.close()
    _log_table("[build_dimensions] rows (loaded includes the Unknown -1 row)", rows,
               ["table", "rows_read", "rows_rejected", "rows_loaded"])


def build_fact(**_):
    _run_sql_file("03_fact.sql")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM clean.order_items")
            read = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mart.fact_sales")
            loaded = cur.fetchone()[0]
            cur.execute("SELECT segment, COUNT(*) FROM mart.dim_customer WHERE customer_key <> -1 GROUP BY 1 ORDER BY 2 DESC")
            seg = cur.fetchall()
    finally:
        conn.close()
    _log_table("[build_fact] FactSales", [("fact_sales", read, read - loaded, loaded)],
               ["table", "rows_read", "rows_rejected", "rows_loaded"])
    _log_table("[build_fact] RFM segments written to dim_customer", seg, ["segment", "customers"])


def quality_checks(**_):
    statements = _split_statements((SQL_DIR / "04_checks.sql").read_text(encoding="utf-8"))
    failed = []
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
                if cur.description is None:
                    continue
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                _log_table("[quality_checks]", rows, cols)
                if "status" in cols:
                    i = cols.index("status")
                    failed += [r for r in rows if str(r[i]).upper() == "FAIL"]
            # B's reconciliation checks (handoff section 5.4), logged for the judges, not a gate
            cur.execute("SELECT (SELECT COUNT(*) FROM clean.payments WHERE is_primary::text = '1'), (SELECT COUNT(*) FROM clean.orders)")
            prim, orders = cur.fetchone()
            log.info("[quality_checks] info: primary payments = %s, clean orders = %s", prim, orders)
    finally:
        conn.close()
    if failed:
        raise AirflowException(f"{len(failed)} quality check(s) FAILED: {failed}")
    log.info("[quality_checks] all checks PASS")


def publish_metrics(**_):
    _run_sql_file("05_metrics.sql")
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM mart.v_kpi_overall")
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
    finally:
        conn.close()
    for c, v in zip(cols, row or []):
        log.info("[publish_metrics] %-22s %s", c, v)


def verify_cleaned_data_unchanged(ti, **_):
    recorded = (ti.xcom_pull(task_ids="clean") or {}).get("fingerprint")
    if recorded is None:
        raise AirflowException("no fingerprint recorded by the clean task")
    now = _fingerprint(OUT_DIR)
    diff = sorted(n for n in set(recorded) | set(now) if recorded.get(n) != now.get(n))
    if diff:
        raise AirflowException(f"cleaned files in out/ changed after the clean task: {diff}")
    log.info("[verify] %d cleaned file(s) in %s unchanged since the clean task (sha256 match)", len(now), OUT_DIR)


# ------------------------------------------------------------------ DAG
default_args = {
    "owner": "nexusmart_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="nexusmart_analytics_pipeline",
    description="NexusMart: raw CSV -> Python cleaning -> Postgres star schema -> quality checks -> KPI views",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule=None,              # run on demand (UI button or `airflow dags trigger`)
    catchup=False,
    max_active_runs=1,          # two runs at once could race on out/
    tags=["nexusmart", "codeconnect26"],
    doc_md=__doc__,
) as dag:
    # data checks are deterministic: retrying them only wastes time
    t_extract = PythonOperator(task_id="extract", python_callable=extract, retries=0)
    t_validate = PythonOperator(task_id="validate_raw", python_callable=validate_raw, retries=0)
    t_clean = PythonOperator(task_id="clean", python_callable=clean, retries=0)
    t_contract = PythonOperator(task_id="check_contract", python_callable=check_contract, retries=0)
    t_load = PythonOperator(task_id="load_staging", python_callable=load_staging)
    t_dims = PythonOperator(task_id="build_dimensions", python_callable=build_dimensions)
    t_fact = PythonOperator(task_id="build_fact", python_callable=build_fact)
    t_quality = PythonOperator(task_id="quality_checks", python_callable=quality_checks, retries=0)
    t_metrics = PythonOperator(task_id="publish_metrics", python_callable=publish_metrics)
    t_verify = PythonOperator(task_id="verify_cleaned_data_unchanged",
                              python_callable=verify_cleaned_data_unchanged, retries=0)

    (t_extract >> t_validate >> t_clean >> t_contract >> t_load
     >> t_dims >> t_fact >> t_quality >> t_metrics >> t_verify)
