"""Type contract for the clean tables (Person B -> Person A / C).

One place that says, for every column of out/*.csv: Postgres type, pandas dtype, PK, nullable.
  python src/clean/clean_schema.py sql  > sql/clean_schema.sql   # CREATE TABLE statements (schema `clean`)
  python src/clean/clean_schema.py check out                     # verify out/*.csv match the contract (exit 1 if not)

Design choices
* ids are TEXT (O0000001, C000001 ...): never cast to int, leading zeros / prefixes must survive.
* city_id, ship_city_id, birth_year are INTEGER (blank = NULL).
* money is NUMERIC(14,2), flags are SMALLINT (0/1), dates are DATE (ISO yyyy-mm-dd).
* NO foreign keys on orders.customer_id / order_items.product_id: orphans are KEPT on purpose (flag
  orphan_customer / orphan_product = 1) and are mapped to Unknown (-1) in the warehouse dims, not rejected.
* Empty CSV cell = NULL. Load with COPY ... CSV HEADER (empty unquoted field = NULL by default).
"""
import os
import sys

# column, postgres type, pandas dtype
T, I, S, D, N, F = "TEXT", "INTEGER", "SMALLINT", "DATE", "NUMERIC(14,2)", "NUMERIC(8,4)"
CONTRACT = {
    "locations": dict(pk="city_id", cols=[
        ("city_id", I), ("city", T), ("province", T), ("region", T),
        ("latitude", "NUMERIC(9,6)"), ("longitude", "NUMERIC(9,6)"), ("population_tier", T)]),
    "sellers": dict(pk="seller_id", cols=[
        ("seller_id", T), ("seller_name", T), ("join_date", D), ("seller_tier", T), ("city_id", I),
        ("rating", "NUMERIC(3,1)")]),
    "products": dict(pk="product_id", cols=[
        ("product_id", T), ("product_name", T), ("category", T), ("sub_category", T), ("brand", T),
        ("list_price", N), ("cost_price", N), ("weight_kg", "NUMERIC(8,3)"), ("seller_id", T), ("cost_imputed", S)]),
    "product_map": dict(pk="product_id", cols=[("product_id", T), ("master_id", T), ("match_rule", T)]),
    "customers": dict(pk="customer_id", cols=[
        ("customer_id", T), ("full_name", T), ("email", T), ("phone", T), ("gender", T),
        ("registration_date", D), ("city_id", I), ("birth_year", I)]),
    "customer_map": dict(pk="customer_id", cols=[("customer_id", T), ("master_id", T), ("match_rule", T)]),
    "orders": dict(pk="order_id", cols=[
        ("order_id", T), ("customer_id", T), ("customer_id_orig", T), ("order_date", D), ("order_status", T),
        ("ship_city_id", I), ("order_total", N), ("discount_code", T), ("discount_pct", F), ("channel", T),
        ("date_repair", T), ("orphan_customer", S), ("order_total_calc", N)]),
    "order_items": dict(pk="order_item_id", cols=[
        ("order_item_id", T), ("order_id", T), ("product_id", T), ("product_id_orig", T), ("seller_id", T),
        ("quantity", I), ("unit_price", N), ("discount_amount", N), ("gross_amount", N), ("net_amount", N),
        ("qty_fix", T), ("price_fix", T), ("orphan_product", S), ("orphan_seller", S), ("unit_cost", N), ("cost_source", T)]),
    "payments": dict(pk="payment_id", cols=[
        ("payment_id", T), ("order_id", T), ("payment_method", T), ("payment_status", T), ("amount", N),
        ("payment_date", D), ("amount_fixed", S), ("n_payments", S), ("is_primary", S)]),
    "shipping": dict(pk="shipment_id", cols=[
        ("shipment_id", T), ("order_id", T), ("courier", T), ("shipped_date", D), ("delivered_date", D),
        ("shipping_fee", N), ("delivery_status", T), ("shipping_days", I), ("date_fix", T), ("fee_imputed", S)]),
    "returns": dict(pk="return_id", cols=[
        ("return_id", T), ("order_item_id", T), ("return_date", D), ("return_reason", T), ("return_status", T),
        ("refund_amount", N), ("is_valid_return", S), ("refund_fixed", S), ("date_fixed", S)]),
}
# load order (parents first) - only matters if you add real foreign keys later
LOAD_ORDER = ["locations", "sellers", "products", "product_map", "customers", "customer_map",
              "orders", "order_items", "payments", "shipping", "returns"]
# soft foreign keys: checked by `check` (orphans listed), never enforced in the database
SOFT_FKS = [("order_items", "order_id", "orders", "order_id"), ("payments", "order_id", "orders", "order_id"),
            ("shipping", "order_id", "orders", "order_id"), ("returns", "order_item_id", "order_items", "order_item_id")]

_PD = {T: "string", I: "Int64", S: "Int64", D: "date"}


def columns(table):
    return [c for c, _ in CONTRACT[table]["cols"]]


def pandas_dtypes(table):
    """dtype dict for pd.read_csv (dates are parsed separately: parse_dates=date_columns(table))."""
    out = {}
    for c, t in CONTRACT[table]["cols"]:
        if t in (T,):
            out[c] = "string"
        elif t in (I, S):
            out[c] = "Int64"
        elif t.startswith("NUMERIC"):
            out[c] = "float64"
    return out


def date_columns(table):
    return [c for c, t in CONTRACT[table]["cols"] if t == D]


def ddl(schema="clean"):
    lines = [f"CREATE SCHEMA IF NOT EXISTS {schema};", ""]
    for t in LOAD_ORDER:
        spec = CONTRACT[t]
        body = [f"    {c:<18} {typ}" + (" PRIMARY KEY" if c == spec["pk"] else "") for c, typ in spec["cols"]]
        lines.append(f"CREATE TABLE IF NOT EXISTS {schema}.{t} (\n" + ",\n".join(body) + "\n);\n")
    return "\n".join(lines)


def check(out_dir="out"):
    """Return a list of problems (empty = out/*.csv honour the contract). Safe to call from the DAG."""
    import pandas as pd
    problems, frames = [], {}
    for t in LOAD_ORDER:
        path = os.path.join(out_dir, f"{t}.csv")
        if not os.path.exists(path):
            problems.append(f"{t}.csv missing")
            continue
        df = pd.read_csv(path, dtype="string", keep_default_na=False)
        df = df.replace("", pd.NA)
        frames[t] = df
        want = columns(t)
        if list(df.columns) != want:
            problems.append(f"{t}: columns differ. missing={[c for c in want if c not in df.columns]} extra={[c for c in df.columns if c not in want]}")
            continue
        pk = CONTRACT[t]["pk"]
        if df[pk].isna().any() or df[pk].duplicated().any():
            problems.append(f"{t}: primary key {pk} has NULL or duplicate values")
        for c, typ in CONTRACT[t]["cols"]:
            s = df[c].dropna()
            if typ in (I, S):
                bad = pd.to_numeric(s, errors="coerce")
                if bad.isna().any() or (bad % 1 != 0).any():
                    problems.append(f"{t}.{c}: not integer (e.g. {s[bad.isna() | (bad % 1 != 0)].iloc[0]!r})")
            elif typ.startswith("NUMERIC"):
                if pd.to_numeric(s, errors="coerce").isna().any():
                    problems.append(f"{t}.{c}: not numeric")
            elif typ == D:
                if pd.to_datetime(s, format="%Y-%m-%d", errors="coerce").isna().any():
                    problems.append(f"{t}.{c}: not an ISO date yyyy-mm-dd")
    for ct, cc, pt, pc in SOFT_FKS:
        if ct in frames and pt in frames:
            n = int((~frames[ct][cc].isin(set(frames[pt][pc].dropna()))).sum())
            if n:
                problems.append(f"{ct}.{cc} -> {pt}.{pc}: {n} orphan rows")
    return problems


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sql"
    if cmd == "sql":
        print(ddl())
    elif cmd == "check":
        probs = check(sys.argv[2] if len(sys.argv) > 2 else "out")
        print("\n".join(probs) if probs else "clean_schema: OK (all 11 tables match the contract)")
        sys.exit(1 if probs else 0)
    else:
        sys.exit("usage: clean_schema.py sql | check <out_dir>")
