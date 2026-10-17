"""NexusMart cleaning pipeline (pure Python / pandas, every fix is logged).

run(raw_dir) -> dict of clean DataFrames + 'dq_log' + 'reject'.
Natural keys are kept here; surrogate keys and the star schema are built in SQL.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import config as C
from toolkit import DQ, parse_dates, to_number, canon_labels, dedup_exact, customer_merge_map

TABLES = ["customers", "products", "sellers", "locations", "orders",
          "order_items", "payments", "shipping", "returns"]
VF, VT = pd.Timestamp(C.VALID_FROM), pd.Timestamp(C.VALID_TO)


def read_raw(d):
    """All columns read as text so nothing is silently coerced at load time."""
    out = {}
    for t in TABLES:
        df = pd.read_csv(Path(d) / f"{t}.csv", dtype=str)
        df.columns = [c.strip().lower() for c in df.columns]
        out[t] = df
    return out


def canon_col(df, col, key, dq, table, unknown="Unknown"):
    before = df[col]
    after, unmatched = canon_labels(before, C.CANON[key], C.ALIASES.get(key), unknown=unknown)
    changed = int((before.fillna("").astype(str) != after).sum())
    dq.log("label_variants", table, col, before.nunique(), after.nunique(),
           f"mapped to canonical set {C.CANON[key]}; empty/unmatched -> {unknown}"
           + (f"; UNMATCHED LABELS: {unmatched}" if unmatched else ""), affected=changed)
    df[col] = after
    return df


def strip_ids(df, cols):
    for c in cols:
        df[c] = df[c].astype("string").str.strip()
    return df


# ------------------------------------------------------------------ locations
def clean_locations(df, dq):
    t = "locations"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["city_id"])
    df = df.drop_duplicates("city_id")
    df["city"] = df["city"].astype("string").str.strip()
    df = canon_col(df, "province", "province", dq, t)
    for c in ("region", "population_tier"):
        df[c] = df[c].astype("string").str.strip().fillna("Unknown")
    df["latitude"], df["longitude"] = to_number(df["latitude"]), to_number(df["longitude"])
    return df.reset_index(drop=True)


# -------------------------------------------------------------------- sellers
def clean_sellers(df, dq):
    t = "sellers"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["seller_id", "city_id"]).drop_duplicates("seller_id")
    df = canon_col(df, "seller_tier", "seller_tier", dq, t)
    df["join_date"] = parse_dates(df["join_date"])
    r = to_number(df["rating"])
    bad = r.notna() & ~r.between(*C.RATING)
    dq.log("rating_out_of_range", t, "rating", int(bad.sum()), 0,
           f"valid range {C.RATING}; set to NULL", affected=int(bad.sum()))
    df["rating"] = r.mask(bad)
    return df.reset_index(drop=True)


# ------------------------------------------------------------------ customers
def normalise_phone(s):
    d = s.astype("string").str.replace(r"\D", "", regex=True)
    d = d.where(~(d.str.startswith("92") & (d.str.len() == 12)), "0" + d.str[2:])
    d = d.where(~((d.str.len() == 10) & d.str.startswith("3")), "0" + d)
    return d.where(d.str.len() == 11)


def clean_customers(df, dq):
    t = "customers"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["customer_id", "city_id"]).drop_duplicates("customer_id")
    df["full_name"] = df["full_name"].astype("string").str.strip().str.title()
    em = df["email"].astype("string").str.strip().str.lower()
    bad_em = em.notna() & ~em.str.contains("@", na=False)
    dq.log("bad_email", t, "email", int(bad_em.sum()), 0, "no '@' -> NULL", affected=int(bad_em.sum()))
    df["email"] = em.mask(bad_em)
    ph = normalise_phone(df["phone"])
    dq.log("phone_format", t, "phone", int(df["phone"].notna().sum()), int(ph.notna().sum()),
           "normalised to 03XXXXXXXXX; unparseable -> NULL",
           affected=int((df["phone"].notna() & ph.isna()).sum()))
    df["phone"] = ph
    df = canon_col(df, "gender", "gender", dq, t)
    reg = parse_dates(df["registration_date"])
    fut = reg > VT
    dq.log("registration_in_future", t, "registration_date", int(fut.sum()), 0,
           f"after {C.VALID_TO} -> NULL", affected=int(fut.sum()))
    df["registration_date"] = reg.mask(fut)
    by = to_number(df["birth_year"])
    badby = by.notna() & ~by.between(*C.BIRTH_YEAR)
    dq.log("birth_year_out_of_range", t, "birth_year", int(badby.sum()), 0,
           f"valid {C.BIRTH_YEAR}; set to NULL", affected=int(badby.sum()))
    df["birth_year"] = by.mask(badby)

    # --- entity resolution: same email OR same phone (never name alone) ---
    cmap = customer_merge_map(df, "customer_id", "email", "phone")
    m = dict(zip(cmap.dup_id, cmap.master_id))
    df["master_id"] = df["customer_id"].map(m).fillna(df["customer_id"])
    n0 = len(df)
    df = df.sort_values("customer_id")
    reg_min = df.groupby("master_id")["registration_date"].min()
    merged = df.groupby("master_id", as_index=False).first()      # first non-null per column
    merged["registration_date"] = merged["master_id"].map(reg_min)
    merged["customer_id"] = merged["master_id"]
    merged = merged.drop(columns="master_id")
    dq.log("duplicate_customers", t, "email/phone", n0, len(merged),
           "merged by normalised email or phone (ids sharing >5 customers ignored as placeholders); "
           "mapping kept in clean.customer_map", affected=n0 - len(merged))
    return merged.reset_index(drop=True), cmap


# ------------------------------------------------------------------- products
def clean_products(df, dq):
    t = "products"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["product_id", "seller_id"]).drop_duplicates("product_id")
    df["product_name"] = df["product_name"].astype("string").str.strip()
    df = canon_col(df, "category", "category", dq, t)
    for c in ("sub_category", "brand"):
        df[c] = df[c].astype("string").str.strip().fillna("Unknown")
    lp, cp, w = to_number(df["list_price"]), to_number(df["cost_price"]), to_number(df["weight_kg"])
    bad_lp = lp.isna() | (lp <= 0)
    dq.log("bad_list_price", t, "list_price", int(bad_lp.sum()), 0,
           "<=0 or unparseable -> NULL (lines then repaired from order_total or rejected)",
           affected=int(bad_lp.sum()))
    lp = lp.mask(bad_lp)
    bad_cp = cp.notna() & ((cp <= 0) | (cp > lp))
    dq.log("cost_gt_list_or_nonpositive", t, "cost_price", int(bad_cp.sum()), 0,
           "cost > list price or <=0 -> NULL then imputed", affected=int(bad_cp.sum()))
    cp = cp.mask(bad_cp)
    ratio = (cp / lp)
    med = ratio.groupby(df["category"]).transform("median").fillna(ratio.median())
    miss = cp.isna() & lp.notna()
    df["cost_imputed"] = miss
    cp = cp.fillna((lp * med).round(0))
    dq.log("missing_cost_price", t, "cost_price", int(miss.sum()), 0,
           "imputed = list_price x median(cost/list) of the category; flagged cost_imputed",
           affected=int(miss.sum()))
    badw = w.notna() & ((w <= 0) | (w > 100))
    dq.log("weight_out_of_range", t, "weight_kg", int(badw.sum()), 0, "<=0 or >100 -> NULL",
           affected=int(badw.sum()))
    df["list_price"], df["cost_price"], df["weight_kg"] = lp, cp, w.mask(badw)

    # --- duplicate products: same normalised name + brand + category ---
    key = (df["product_name"].str.lower().str.replace(r"[^a-z0-9]+", "", regex=True)
           + "|" + df["brand"].str.lower() + "|" + df["category"])
    df["master_id"] = df.sort_values("product_id").groupby(key)["product_id"].transform("first")
    pmap = df.loc[df.product_id != df.master_id, ["product_id", "master_id"]].rename(
        columns={"product_id": "dup_id"})
    n0 = len(df)
    out = df[df.product_id == df.master_id].drop(columns="master_id")
    dq.log("duplicate_products", t, "name+brand+category", n0, len(out),
           "merged by normalised name+brand+category; mapping kept in clean.product_map",
           affected=n0 - len(out))
    return out.reset_index(drop=True), pmap.reset_index(drop=True)


# ------------------------------------------------------------------- payments
def clean_payments(df, dq):
    t = "payments"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["payment_id", "order_id"]).drop_duplicates("payment_id")
    df = canon_col(df, "payment_method", "payment_method", dq, t)
    df = canon_col(df, "payment_status", "payment_status", dq, t)
    a = to_number(df["amount"])
    bad = a.notna() & (a <= 0)
    dq.log("bad_amount", t, "amount", int((bad | a.isna()).sum()), 0,
           "<=0 / sentinel / unparseable -> NULL", affected=int((bad | a.isna()).sum()))
    df["amount"] = a.mask(bad)
    df["payment_date"] = parse_dates(df["payment_date"])
    return df.reset_index(drop=True)


# ------------------------------------------------------------------- shipping
def clean_shipping(df, dq):
    t = "shipping"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["shipment_id", "order_id"]).drop_duplicates("order_id")
    df = canon_col(df, "courier", "courier", dq, t)
    df = canon_col(df, "delivery_status", "delivery_status", dq, t)
    df["shipped_date"] = parse_dates(df["shipped_date"])
    df["delivered_date"] = parse_dates(df["delivered_date"])
    f = to_number(df["shipping_fee"])
    bad = f.isna() | (f <= 0)
    med = f.where(~bad).groupby(df["courier"]).transform("median")
    df["fee_imputed"] = bad
    df["shipping_fee"] = f.mask(bad).fillna(med)
    dq.log("bad_shipping_fee", t, "shipping_fee", int(bad.sum()), 0,
           "NULL/sentinel/<=0 -> courier median; flagged fee_imputed", affected=int(bad.sum()))
    days = (df["delivered_date"] - df["shipped_date"]).dt.days
    neg = (days < 0).sum()
    long_ = (days > C.SHIP_DAYS_MAX).sum()
    ok = days.between(0, C.SHIP_DAYS_MAX)
    df["shipping_days"] = days.where(ok)
    dq.log("impossible_delivery_dates", t, "delivered_date", int(neg + long_), 0,
           f"delivered<shipped ({neg}) or >{C.SHIP_DAYS_MAX} days ({long_}) -> shipping_days NULL",
           affected=int(neg + long_))
    return df.reset_index(drop=True)


# --------------------------------------------------------------------- orders
def clean_orders(df, dq, pay, ship, cust_map, cust_ids):
    t = "orders"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["order_id", "customer_id", "ship_city_id"]).drop_duplicates("order_id")
    df = canon_col(df, "order_status", "order_status", dq, t)
    df = canon_col(df, "channel", "channel", dq, t)
    od = parse_dates(df["order_date"])
    unparseable = od.isna()
    in_rng = od.between(VF, VT)
    need = ~in_rng
    # repair from other tables: first valid payment date, else shipped date
    p = pay.loc[pay.payment_date.between(VF, VT)].groupby("order_id")["payment_date"].min()
    s = ship.loc[ship.shipped_date.between(VF, VT)].set_index("order_id")["shipped_date"]
    fix = df["order_id"].map(p).fillna(df["order_id"].map(s))
    od = od.where(~need, fix)
    repaired = need & od.notna()
    dq.log("bad_order_date", t, "order_date", int(need.sum()), int((need & od.isna()).sum()),
           "impossible/out-of-range dates repaired from first payment date else shipped date; "
           "the rest rejected", affected=int(repaired.sum()))
    df["order_date"], df["order_date_repaired"] = od, repaired
    rej = df[od.isna()].copy()
    rej_reason = np.where(unparseable[od.isna()], "BAD_DATE", "DATE_OUT_OF_RANGE")
    for reason in ("BAD_DATE", "DATE_OUT_OF_RANGE"):
        dq.reject(rej[rej_reason == reason], t, reason)
    df = df[od.notna()].copy()
    tot = to_number(df["order_total"])
    badt = tot.isna() | (tot <= 0)
    dq.log("bad_order_total", t, "order_total", int(badt.sum()), 0,
           "sentinel/<=0/unparseable -> NULL (recomputed from lines in clean.orders.order_total_calc)",
           affected=int(badt.sum()))
    df["order_total"] = tot.mask(badt)
    df["discount_pct"] = (df["discount_code"].astype("string").str.extract(r"(\d+)")[0]
                          .astype(float).fillna(0))
    m = dict(zip(cust_map.dup_id, cust_map.master_id))
    df["customer_id"] = df["customer_id"].map(m).fillna(df["customer_id"])
    df["orphan_customer"] = ~df["customer_id"].isin(cust_ids)
    dq.log("orphan_customer", t, "customer_id", int(df["orphan_customer"].sum()), 0,
           "customer not in customers -> kept, mapped to Unknown customer; flagged orphan_customer",
           affected=int(df["orphan_customer"].sum()))
    return df.reset_index(drop=True), set(rej["order_id"])


# ---------------------------------------------------------------- order items
def _repair_with_order_total(it, need, which):
    """If an order has exactly one bad line, the order_total pins it down."""
    net_ok = np.where(need, 0.0, it["quantity"] * it["unit_price"] * (1 - it["discount_pct"] / 100))
    other = pd.Series(net_ok, index=it.index).groupby(it["order_id"]).transform("sum")
    n_need = need.groupby(it["order_id"]).transform("sum")
    remaining = it["order_total"] - other
    f = 1 - it["discount_pct"] / 100
    if which == "qty":
        implied = (remaining / (it["unit_price"] * f)).round()
        ok = implied.between(1, C.QTY_MAX) & ((implied * it["unit_price"] * f - remaining).abs() <= 0.02 * remaining)
    else:
        implied = remaining / (it["quantity"] * f)
        ok = implied > 0
        if "list_price" in it:
            r = implied / it["list_price"]
            ok &= r.between(*C.PRICE_RATIO) | it["list_price"].isna()
    ok &= need & (n_need == 1) & remaining.gt(0) & it["order_total"].notna()
    return implied.where(ok), ok


def clean_order_items(df, dq, orders, rejected_orders, prods, pmap, seller_ids):
    t = "order_items"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["order_item_id", "order_id", "product_id", "seller_id"]).drop_duplicates("order_item_id")
    # --- parents ---
    par = df["order_id"].isin(rejected_orders)
    miss = ~df["order_id"].isin(orders["order_id"]) & ~par
    dq.reject(df[par], t, "PARENT_ORDER_REJECTED")
    dq.reject(df[miss], t, "ORPHAN_ORDER")
    dq.log("rejected_or_orphan_order", t, "order_id", len(df), int((~par & ~miss).sum()),
           "line's order was rejected (bad date) or does not exist -> reject table",
           affected=int((par | miss).sum()))
    df = df[~par & ~miss].copy()
    # --- keys ---
    m = dict(zip(pmap.dup_id, pmap.master_id))
    df["product_id"] = df["product_id"].map(m).fillna(df["product_id"])
    df = df.merge(prods[["product_id", "list_price", "cost_price"]], on="product_id", how="left")
    df["orphan_product"] = ~df["product_id"].isin(prods["product_id"])
    df["orphan_seller"] = ~df["seller_id"].isin(seller_ids)
    dq.log("orphan_product", t, "product_id", int(df["orphan_product"].sum()), 0,
           "product not in products -> kept, mapped to Unknown product", affected=int(df["orphan_product"].sum()))
    dq.log("orphan_seller", t, "seller_id", int(df["orphan_seller"].sum()), 0,
           "seller not in sellers -> kept, mapped to Unknown seller", affected=int(df["orphan_seller"].sum()))
    df = df.merge(orders[["order_id", "order_total", "discount_pct"]], on="order_id", how="left")
    # --- price ---
    p = to_number(df["unit_price"])
    lo, hi = C.PRICE_RATIO
    ratio = p / df["list_price"]
    badp = p.isna() | (p <= 0) | ((ratio > hi) | (ratio < lo))
    by_list = badp & df["list_price"].notna()
    p = p.where(~by_list, df["list_price"])
    df["unit_price"], df["price_repaired"] = p, by_list
    q = to_number(df["quantity"])
    neg = q < 0
    q = q.abs().round()
    df["quantity"] = q
    stillp = badp & ~by_list
    # price via order_total (needs valid quantity)
    qbad = q.isna() | (q == 0) | (q > C.QTY_MAX)
    implied, okp = _repair_with_order_total(df.assign(unit_price=p.where(~stillp)), stillp & ~qbad, "price")
    df.loc[okp, "unit_price"] = implied[okp]
    df.loc[okp, "price_repaired"] = True
    still_bad_price = stillp & ~okp
    dq.log("bad_unit_price", t, "unit_price", int(badp.sum()), int(still_bad_price.sum()),
           f"sentinel/<=0/ratio to list_price outside {C.PRICE_RATIO}: replaced by list_price "
           f"({int(by_list.sum())}), else implied by order_total ({int(okp.sum())}), else rejected BAD_PRICE",
           affected=int(badp.sum() - still_bad_price.sum()))
    dq.reject(df[still_bad_price], t, "BAD_PRICE")
    df = df[~still_bad_price].copy()
    q = df["quantity"]
    # --- quantity ---
    dq.log("negative_quantity", t, "quantity", int(neg.sum()), 0,
           "sign flip assumed: abs(quantity) (validated against order_total)", affected=int(neg.sum()))
    qbad = q.isna() | (q == 0) | (q > C.QTY_MAX)
    implied, okq = _repair_with_order_total(df, qbad, "qty")
    df.loc[okq, "quantity"] = implied[okq]
    df["qty_repaired"] = okq
    still_bad_q = qbad & ~okq
    dq.log("quantity_outlier", t, "quantity", int(qbad.sum()), int(still_bad_q.sum()),
           f"zero/NULL/>{C.QTY_MAX} units: implied by order_total when exactly one bad line "
           f"({int(okq.sum())}), else rejected BAD_QTY", affected=int(okq.sum()))
    dq.reject(df[still_bad_q], t, "BAD_QTY")
    df = df[~still_bad_q].copy()
    # --- discount ---
    gross = df["quantity"] * df["unit_price"]
    d = to_number(df["discount_amount"])
    calc = (gross * df["discount_pct"] / 100).round()
    bad_d = d.isna() | (d < 0) | (d > gross)
    df["discount_amount"] = d.where(~bad_d, calc)
    df["discount_filled"] = bad_d
    dq.log("missing_or_invalid_discount", t, "discount_amount", int(bad_d.sum()), 0,
           "NULL/negative/>gross -> quantity x unit_price x order discount_code%", affected=int(bad_d.sum()))
    df["gross_amount"] = gross
    df["net_amount"] = gross - df["discount_amount"]
    return df.drop(columns=["order_total", "discount_pct"]).reset_index(drop=True)


# -------------------------------------------------------------------- returns
def clean_returns(df, dq, items):
    t = "returns"
    df = dedup_exact(df, dq, t)
    df = strip_ids(df, ["return_id", "order_item_id"]).drop_duplicates("return_id")
    orphan = ~df["order_item_id"].isin(items["order_item_id"])
    dq.reject(df[orphan], t, "ORPHAN_RETURN")
    dq.log("orphan_return", t, "order_item_id", len(df), int((~orphan).sum()),
           "order line not in order_items -> reject table", affected=int(orphan.sum()))
    df = df[~orphan].copy()
    df = canon_col(df, "return_status", "return_status", dq, t)
    df = canon_col(df, "return_reason", "return_reason", dq, t)
    df["return_date"] = parse_dates(df["return_date"])
    df["is_valid_return"] = df["return_status"] != "Rejected"
    net = df["order_item_id"].map(items.set_index("order_item_id")["net_amount"])
    r = to_number(df["refund_amount"])
    zero = df["is_valid_return"] & (r.isna() | (r <= 0))
    over = df["is_valid_return"] & (r > net)
    dq.log("refund_zero_or_missing", t, "refund_amount", int(zero.sum()), 0,
           "valid return with 0/NULL refund -> full line net amount (assumption: full refund)",
           affected=int(zero.sum()))
    dq.log("refund_exceeds_line", t, "refund_amount", int(over.sum()), 0,
           "refund > line net amount -> capped at line net amount", affected=int(over.sum()))
    r = r.mask(zero, net).mask(over, net)
    df["refund_amount"] = r.where(df["is_valid_return"], 0.0)
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------- main
def run(raw_dir):
    dq, raw = DQ(), read_raw(raw_dir)
    loc = clean_locations(raw["locations"], dq)
    sel = clean_sellers(raw["sellers"], dq)
    cus, cmap = clean_customers(raw["customers"], dq)
    prod, pmap = clean_products(raw["products"], dq)
    pay = clean_payments(raw["payments"], dq)
    shp = clean_shipping(raw["shipping"], dq)
    ords, rej_orders = clean_orders(raw["orders"], dq, pay, shp, cmap, set(cus.customer_id))
    items = clean_order_items(raw["order_items"], dq, ords, rej_orders, prod, pmap, set(sel.seller_id))
    # children of rejected orders
    for name, df in (("payments", pay), ("shipping", shp)):
        bad = df["order_id"].isin(rej_orders) | ~df["order_id"].isin(ords["order_id"])
        dq.reject(df[bad], name, "PARENT_ORDER_REJECTED")
        dq.log("orphan_or_rejected_parent", name, "order_id", len(df), int((~bad).sum()),
               "order rejected or missing -> reject table", affected=int(bad.sum()))
        df.drop(df.index[bad], inplace=True)
    ret = clean_returns(raw["returns"], dq, items)
    # order_total_calc: what the lines add up to (used to validate order_total)
    calc = items.groupby("order_id")["net_amount"].sum()
    ords["order_total_calc"] = ords["order_id"].map(calc)
    match = (ords["order_total"] - ords["order_total_calc"]).abs() <= 1
    dq.log("order_total_vs_lines", "orders", "order_total", len(ords), int(match.sum()),
           "orders whose order_total equals sum of cleaned line nets (+-1 PKR); informational check",
           affected=int((~match).sum()))
    return dict(locations=loc, sellers=sel, customers=cus, customer_map=cmap, products=prod,
                product_map=pmap, orders=ords, order_items=items, payments=pay, shipping=shp,
                returns=ret, dq_log=dq.log_df(), reject=dq.reject_df())


def save(res, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, df in res.items():
        df.to_csv(out / f"{name}.csv", index=False)


if __name__ == "__main__":
    res = run(sys.argv[1])
    save(res, sys.argv[2])
    print(res["dq_log"][["issue", "table", "column", "rows_before", "rows_after", "rows_affected"]].to_string())
    print("\nrejects by reason:\n", res["reject"].groupby(["reject_table", "reason_code"]).size())
    print({k: len(v) for k, v in res.items()})
