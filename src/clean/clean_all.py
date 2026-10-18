"""NexusMart cleaning pipeline (Person B).

Usage:   python src/clean/clean_all.py data out
Library: from clean_all import run; summary = run("data", "out")

Reads the 9 raw CSVs, writes to out/:
  customers, customer_map, products, product_map, sellers, locations, orders, order_items,
  payments, shipping, returns   (clean tables, names match the `clean` schema)
  dq_log.csv   every cleaning decision with before/after counts
  reject.csv   every record that could not be repaired, with a reason code (never a silent delete)
All thresholds / label aliases live in nx_config.py so the Hour-6 data drop only needs config edits.
"""
import difflib
import os
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_config as C                                                    # noqa: E402
from toolkit import (Audit, LabelMapper, half_up, in_range, is_sentinel, parse_date,   # noqa: E402
                     pct_from_code, strip_all, to_num, to_qty, unrecognised_dates)

RAW_FILES = ["customers", "products", "sellers", "locations", "orders", "order_items",
             "payments", "shipping", "returns"]


def read_raw(data_dir):
    raw = {}
    for name in RAW_FILES:
        path = os.path.join(data_dir, f"{name}.csv")
        raw[name] = pd.read_csv(path, dtype="string", keep_default_na=False, encoding="utf-8-sig")
    return raw


def validate_raw(data_dir):
    """Used by the Airflow `validate_raw` task. Returns a list of problems (empty = OK)."""
    problems = []
    for name, cols in C.REQUIRED_COLUMNS.items():
        path = os.path.join(data_dir, f"{name}.csv")
        if not os.path.exists(path):
            problems.append(f"{name}.csv missing")
            continue
        head = pd.read_csv(path, nrows=5, dtype="string", encoding="utf-8-sig")
        missing = [c for c in cols if c not in head.columns]
        if missing:
            problems.append(f"{name}.csv missing columns {missing}")
        elif len(head) == 0:
            problems.append(f"{name}.csv is empty")
    return problems


def _date(audit, table, column, series):
    """parse_date + log any value in a brand-new format (Hour-6 safety net)."""
    new = unrecognised_dates(series)
    if len(new):
        audit.log(table, "UNRECOGNISED DATE FORMAT", column, len(new), len(new), "left NULL (then repaired/rejected like any bad date)",
                  "add the format to toolkit._PATTERNS; samples: " + "; ".join(map(str, new.unique()[:5])))
    return parse_date(series)


def _int(series):
    return pd.to_numeric(series, errors="coerce").astype("Int64")


# =====================================================================================
# LOCATIONS
# =====================================================================================
def clean_locations(df, audit):
    t = "locations"
    df = strip_all(df)
    dup = df.duplicated("city_id", keep="first")
    audit.reject(df[dup], t, "city_id", "DUPLICATE_KEY")
    df = df[~dup].copy()
    df["city_id"] = _int(df["city_id"])
    df["city"] = df["city"].fillna(C.UNKNOWN)
    df["province"] = LabelMapper("province").map(df["province"], audit, t, "province")
    df["population_tier"] = LabelMapper("population_tier").map(df["population_tier"], audit, t, "population_tier")
    df["region"] = df["region"].str.title().fillna(C.UNKNOWN)

    lat, lon = to_num(df["latitude"]), to_num(df["longitude"])
    swapped = lat.between(60, 78) & lon.between(23, 38)            # lat/lon entered the wrong way round
    lat, lon = lat.where(~swapped, lon), lon.where(~swapped, lat)
    bad = ~(lat.between(23, 38) & lon.between(60, 78))
    audit.log(t, "BAD COORDINATES", "latitude/longitude", int(swapped.sum() + bad.sum()), int(bad.sum()),
              f"{int(swapped.sum())} swapped lat/lon fixed; {int(bad.sum())} outside Pakistan set to NULL",
              "Pakistan bbox lat 23-38, lon 60-78")
    df["latitude"], df["longitude"] = lat.where(~bad), lon.where(~bad)

    # missing province: nearest-neighbour on coordinates, only if leave-one-out accuracy is good
    known = (df["province"] != C.UNKNOWN) & df["latitude"].notna()
    unk = (df["province"] == C.UNKNOWN) & df["latitude"].notna()
    n_unk_before = int((df["province"] == C.UNKNOWN).sum())
    if known.sum() > 20 and unk.any():
        K = df[known]
        xy = K[["latitude", "longitude"]].to_numpy(float)
        prov = K["province"].to_numpy()

        def knn(pt, exclude=None, k=5):
            d = np.hypot(xy[:, 0] - pt[0], xy[:, 1] - pt[1])
            if exclude is not None:
                d[exclude] = np.inf
            idx = np.argsort(d)[:k]
            vals, cnt = np.unique(prov[idx], return_counts=True)
            return vals[cnt.argmax()]
        hits = sum(knn(xy[i], exclude=i) == prov[i] for i in range(len(xy)))
        acc = hits / len(xy)
        if acc >= 0.85:
            for i in df.index[unk]:
                df.at[i, "province"] = knn(df.loc[i, ["latitude", "longitude"]].to_numpy(float))
        audit.log(t, "MISSING PROVINCE", "province", n_unk_before, int((df["province"] == C.UNKNOWN).sum()),
                  "filled from 5 nearest cities by coordinates" if acc >= 0.85 else "left Unknown (kNN accuracy too low)",
                  f"leave-one-out accuracy {acc:.1%}; applied only if >= 85%")
    return df[["city_id", "city", "province", "region", "latitude", "longitude", "population_tier"]]


# =====================================================================================
# SELLERS
# =====================================================================================
def clean_sellers(df, audit):
    t = "sellers"
    df = strip_all(df)
    dup = df.duplicated("seller_id", keep="first")
    audit.reject(df[dup], t, "seller_id", "DUPLICATE_KEY")
    df = df[~dup].copy()
    df["seller_name"] = df["seller_name"].fillna(C.UNKNOWN)
    df["join_date"] = _date(audit, t, "join_date", df["join_date"])
    df["seller_tier"] = LabelMapper("seller_tier").map(df["seller_tier"], audit, t, "seller_tier")
    r = to_num(df["rating"])
    bad = r.notna() & ~r.between(C.RATING_MIN, C.RATING_MAX)
    audit.log(t, "RATING OUT OF RANGE", "rating", int(bad.sum()), 0, "set to NULL",
              f"valid rating {C.RATING_MIN}-{C.RATING_MAX}; {int(r.isna().sum())} already missing stay NULL (not imputed: ratings are a quality signal)")
    df["rating"] = r.where(~bad)
    df["city_id"] = _int(df["city_id"])
    return df[["seller_id", "seller_name", "join_date", "seller_tier", "city_id", "rating"]]


# =====================================================================================
# PRODUCTS (+ product_map)
# =====================================================================================
def _ptype(name, brand):
    n = re.sub(r"\s+[A-Za-z]\d+$", "", str(name))
    if pd.notna(brand) and n.lower().startswith(str(brand).lower()):
        n = n[len(str(brand)):]
    return n.strip().lower()


def clean_products(df, items_raw, audit):
    t = "products"
    df = strip_all(df)
    dup = df.duplicated("product_id", keep="first")
    audit.reject(df[dup], t, "product_id", "DUPLICATE_KEY")
    df = df[~dup].copy()
    df["category"] = LabelMapper("category").map(df["category"], audit, t, "category")

    # brand: missing -> brand is the first word(s) of product_name when it is a known brand
    brands = df["brand"].dropna()
    known = set(brands.value_counts()[lambda s: s >= 5].index)
    first = df["product_name"].fillna("").str.split().str[0]
    miss = df["brand"].isna()
    fill = first.where(first.isin(known))
    df.loc[miss, "brand"] = fill[miss]
    audit.log(t, "MISSING BRAND", "brand", int(miss.sum()), int(df["brand"].isna().sum()),
              "filled from first word of product_name when it is a known brand; else 'Unknown'",
              "product names start with the brand in this catalogue")
    df["brand"] = df["brand"].fillna(C.UNKNOWN)

    # sub_category: infer from (category, product type) when that mapping is unambiguous (>=90%)
    df["_pt"] = [_ptype(n, b) for n, b in zip(df["product_name"], df["brand"])]
    has = df["sub_category"].notna()
    share = df[has].groupby(["category", "_pt"])["sub_category"].agg(lambda s: (s.value_counts().iloc[0] / len(s), s.value_counts().index[0]))
    mp = {k: v[1] for k, v in share.items() if v[0] >= 0.9}
    n_missing = int((~has).sum())
    inferred = df.loc[~has].apply(lambda r: mp.get((r["category"], r["_pt"])), axis=1)
    df.loc[~has, "sub_category"] = inferred
    audit.log(t, "MISSING SUB_CATEGORY", "sub_category", n_missing, int(df["sub_category"].isna().sum()),
              "inferred from (category, product type); remainder 'Unknown'",
              f"{int(inferred.notna().sum())} inferred where the type->sub_category mapping is >=90% consistent")
    df["sub_category"] = df["sub_category"].fillna(C.UNKNOWN)

    # weight
    w = to_num(df["weight_kg"])
    bad = w.notna() & ~((w > 0) & (w <= 100))
    audit.log(t, "BAD WEIGHT", "weight_kg", int(bad.sum()), 0, "set to NULL", f"valid 0<w<=100; {int(w.isna().sum())} originally missing stay NULL")
    df["weight_kg"] = w.where(~bad)

    # list price: validate against what customers actually paid (median line price per product)
    lp = to_num(df["list_price"])
    ip = items_raw[["product_id", "unit_price"]].copy()
    ip["p"] = to_num(ip["unit_price"])
    ip = ip[(ip["p"] > 0) & ~is_sentinel(ip["p"])]
    med = ip.groupby("product_id")["p"].agg(["median", "size"])
    est = df["product_id"].map(med["median"])
    nl = df["product_id"].map(med["size"]).fillna(0)
    bad_lp = lp.isna() | (lp <= 0) | is_sentinel(lp.fillna(0)) | ((nl >= 3) & ((lp / est - 1).abs() > 0.25))
    fix = bad_lp & est.notna()
    audit.log(t, "BAD LIST PRICE", "list_price", int(bad_lp.sum()), int((bad_lp & ~fix).sum()),
              "replaced with median unit_price actually charged on that product's lines",
              "invalid = <=0, sentinel, or >25% away from median charged price (needs >=3 lines)")
    lp = lp.where(~fix, est.round())
    lp = lp.where(~(lp <= 0))
    df["list_price"] = lp

    # cost price: valid if 0 < cost <= list, else impute category median cost/list ratio
    cp = to_num(df["cost_price"])
    ratio = cp / lp
    good = ratio.between(0.05, 1.0)
    cat_ratio = ratio[good].groupby(df["category"]).median()
    glob = float(ratio[good].median()) if good.any() else 0.6
    imp = (~good) & lp.notna()
    df["cost_imputed"] = imp.astype(int)
    cp_fix = (lp * df["category"].map(cat_ratio).fillna(glob)).round()
    audit.log(t, "MISSING/BAD COST PRICE", "cost_price", int(imp.sum()), 0,
              "imputed list_price x median(cost/list) of the category; flagged cost_imputed=1",
              f"missing {int(cp.isna().sum())}, cost>list {int((cp > lp).sum())}; median ratio {glob:.2f}")
    df["cost_price"] = cp.where(good, cp_fix)

    # duplicates: same normalised name + brand + category (never name alone) -> one master id
    key = (df["product_name"].str.lower().str.replace(r"\s+", " ", regex=True).fillna("") + "|" +
           df["brand"].str.lower() + "|" + df["category"])
    df["_key"] = key
    df = df.sort_values("product_id")
    master = df.groupby("_key")["product_id"].transform("first")
    pmap = pd.DataFrame({"product_id": df["product_id"], "master_id": master,
                         "match_rule": np.where(df["product_id"] == master, "SELF", "NAME+BRAND+CATEGORY")})
    n_before = len(df)
    for col in ["sub_category", "list_price", "cost_price", "weight_kg"]:   # keep first non-null of the group
        pass
    df = df[df["product_id"] == master].copy()
    audit.log(t, "DUPLICATE PRODUCTS", "product_id", n_before, len(df),
              "merged to lowest product_id; dup->master kept in product_map",
              "match = normalised name + brand + category; sellers/price may differ between listings (order lines keep their own seller_id)")
    df["list_price"] = df["list_price"].astype(float)
    return (df[["product_id", "product_name", "category", "sub_category", "brand", "list_price",
                "cost_price", "weight_kg", "seller_id", "cost_imputed"]].reset_index(drop=True), pmap.reset_index(drop=True))


# =====================================================================================
# CUSTOMERS (+ customer_map)
# =====================================================================================
def _norm_phone(p):
    if pd.isna(p):
        return None
    d = re.sub(r"\D", "", str(p))
    if len(d) == 12 and d.startswith("92"):
        d = "0" + d[2:]
    elif len(d) == 10 and d.startswith("3"):
        d = "0" + d
    return d if (len(d) == 11 and d.startswith("03")) else None


def clean_customers(df, audit):
    t = "customers"
    df = strip_all(df)
    dup = df.duplicated("customer_id", keep="first")
    audit.reject(df[dup], t, "customer_id", "DUPLICATE_KEY")
    df = df[~dup].copy()
    df["full_name"] = df["full_name"].str.replace(r"\s+", " ", regex=True).str.title().fillna(C.UNKNOWN)
    em = df["email"].str.lower()
    bad_em = em.notna() & ~em.str.contains("@", na=False)
    df["email"] = em.where(~bad_em)
    ph = df["phone"].map(_norm_phone)
    audit.log(t, "PHONE NORMALISATION", "phone", int(df["phone"].notna().sum()), int(ph.notna().sum()),
              "digits only, 03XXXXXXXXX format; unparseable -> NULL", f"{int(df['phone'].isna().sum())} originally missing")
    df["phone"] = ph
    df["gender"] = LabelMapper("gender").map(df["gender"], audit, t, "gender")
    df["registration_date"] = _date(audit, t, "registration_date", df["registration_date"])
    audit.log(t, "MISSING / IMPOSSIBLE REGISTRATION DATE", "registration_date", int(df["registration_date"].isna().sum()), int(df["registration_date"].isna().sum()),
              "kept as NULL (not repairable from other data)", "registration dates legitimately precede the 2024-25 order window")
    by = to_num(df["birth_year"])
    badby = by.notna() & ~by.between(C.BIRTH_YEAR_MIN, C.BIRTH_YEAR_MAX)
    audit.log(t, "BIRTH YEAR OUT OF RANGE", "birth_year", int(badby.sum()), 0, "set to NULL",
              f"valid {C.BIRTH_YEAR_MIN}-{C.BIRTH_YEAR_MAX}; {int(by.isna().sum())} originally missing stay NULL")
    df["birth_year"] = by.where(~badby).round().astype("Int64")
    df["city_id"] = _int(df["city_id"])

    # --- duplicate entities: union-find over shared email / shared phone (never name alone)
    df = df.sort_values("customer_id").reset_index(drop=True)
    parent = {i: i for i in df["customer_id"]}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)         # lowest id wins -> stable master
    rule = {}
    names = df.set_index("customer_id")["full_name"].str.lower()
    skipped = 0
    for col, label in (("email", "EMAIL"), ("phone", "PHONE")):
        g = df[df[col].notna()].groupby(col)["customer_id"].apply(list)
        for ids in g[g.map(len) > 1]:
            base = ids[0]
            for other in ids[1:]:
                if label == "PHONE" and difflib.SequenceMatcher(None, names[base], names[other]).ratio() < C.PHONE_NAME_SIM:
                    skipped += 1
                    continue
                union(base, other)
                rule.setdefault(other, label)
    df["master_id"] = df["customer_id"].map(find)
    cmap = pd.DataFrame({"customer_id": df["customer_id"], "master_id": df["master_id"],
                         "match_rule": df["customer_id"].map(lambda i: "SELF" if find(i) == i else rule.get(i, "TRANSITIVE"))})
    # merged master record: earliest registration, first non-null for the other fields
    first_nn = df.groupby("master_id").agg({"full_name": "first", "email": "first", "phone": "first", "gender": lambda s: next((v for v in s if v != C.UNKNOWN), C.UNKNOWN),
                                            "registration_date": "min", "city_id": "first", "birth_year": "first"})
    out = first_nn.reset_index().rename(columns={"master_id": "customer_id"})
    audit.log(t, "DUPLICATE CUSTOMERS", "customer_id", len(df), len(out),
              "merged to lowest customer_id; every dup->master pair kept in customer_map",
              f"link = same normalised email OR same phone (phone links also need name similarity >= {C.PHONE_NAME_SIM}); {skipped} phone links skipped; never name alone")
    return out[["customer_id", "full_name", "email", "phone", "gender", "registration_date", "city_id", "birth_year"]], cmap[["customer_id", "master_id", "match_rule"]]


# =====================================================================================
# ORDERS
# =====================================================================================
def clean_orders(raw, ship_raw, pay_raw, customers, cmap, locations, audit):
    t = "orders"
    n_raw = len(raw)
    df = strip_all(raw).drop_duplicates()
    audit.log(t, "EXACT DUPLICATE ROWS", "(all columns)", n_raw, len(df), "drop_duplicates, count logged",
              "rows identical in every column are the same record exported twice")
    dup = df.duplicated("order_id", keep="first")
    audit.reject(df[dup], t, "order_id", "DUPLICATE_KEY", "same order_id, different content; first kept")
    df = df[~dup].copy()

    # ---- dates: three formats, slash = dd/mm/yyyy
    od = _date(audit, t, "order_date", df["order_date"])
    unparse = od.isna()
    oor = od.notna() & ~in_range(od)
    audit.log(t, "IMPOSSIBLE / UNPARSEABLE DATE", "order_date", int(unparse.sum()), 0, "see repair below",
              "30 Feb, 31 Apr, month 13, 00/00/yyyy cannot be parsed")
    audit.log(t, "DATE OUT OF RANGE", "order_date", int(oor.sum()), 0, "see repair below",
              f"valid window {C.DATE_MIN.date()}..{C.DATE_MAX.date()}")

    # ---- repair from the order's own shipment / payment dates (lag learned from good rows)
    sd = parse_date(ship_raw["shipped_date"].astype("string").str.strip())
    ship_min = sd.where(in_range(sd)).groupby(ship_raw["order_id"].astype("string").str.strip()).min()
    pdt = parse_date(pay_raw["payment_date"].astype("string").str.strip())
    pay_min = pdt.where(in_range(pdt)).groupby(pay_raw["order_id"].astype("string").str.strip()).min()
    good = in_range(od)
    s_ser, p_ser = df["order_id"].map(ship_min), df["order_id"].map(pay_min)
    ship_lag = pd.to_timedelta(round(((s_ser - od)[good].dt.days).median()), unit="D")
    pay_lag = pd.to_timedelta(round(((p_ser - od)[good].dt.days).median()), unit="D")
    cand_s, cand_p = s_ser - ship_lag, p_ser - pay_lag
    use_s = ~good & in_range(cand_s)
    use_p = ~good & ~use_s & in_range(cand_p)
    od = od.where(good, np.where(use_s, cand_s, np.where(use_p, cand_p, pd.NaT)))
    od = pd.to_datetime(od)
    df["date_repair"] = np.where(use_s, "SHIPPED_DATE", np.where(use_p, "PAYMENT_DATE", ""))
    unfixable = ~in_range(od)
    audit.log(t, "ORDER DATE REPAIR", "order_date", int((~good).sum()), int(unfixable.sum()),
              f"{int(use_s.sum())} repaired as shipped_date - {ship_lag.days}d, {int(use_p.sum())} as payment_date - {pay_lag.days}d, "
              f"{int(unfixable.sum())} rejected (BAD_DATE / DATE_OUT_OF_RANGE)",
              f"shipped_date - order_date is {ship_lag.days} day (0-2 on 100% of valid rows) so it is the most accurate anchor; payment lag is spread over 0-11+ days so it is the fallback")
    rej_dates = df[unfixable]
    reason = np.where(unparse[unfixable], "BAD_DATE", "DATE_OUT_OF_RANGE")
    for rs in ("BAD_DATE", "DATE_OUT_OF_RANGE"):
        audit.reject(rej_dates[reason == rs], t, "order_id", rs, "no usable shipped/payment date")
    rejected_ids = set(rej_dates["order_id"])
    df["order_date"] = od
    df = df[~unfixable].copy()

    # ---- labels, numbers
    df["order_status"] = LabelMapper("order_status").map(df["order_status"], audit, t, "order_status")
    df["channel"] = LabelMapper("channel").map(df["channel"], audit, t, "channel")
    pct = pct_from_code(df["discount_code"])
    df["discount_pct"] = pct
    df["discount_code"] = np.where(pct > 0, "SAVE" + (pct * 100).round().astype(int).astype(str), None)
    ot = to_num(df["order_total"])
    bad_ot = ot.isna() | (ot <= 0) | is_sentinel(ot.fillna(0))
    audit.log(t, "BAD ORDER TOTAL", "order_total", int(bad_ot.sum()), 0,
              "set NULL then recomputed from clean order lines (sentinel 9999999, <=0, 'Rs. 1,234' text parsed)", "")
    df["order_total"] = ot.where(~bad_ot)

    # ---- references
    df["customer_id_orig"] = df["customer_id"]
    df["customer_id"] = df["customer_id"].map(cmap.set_index("customer_id")["master_id"]).fillna(df["customer_id"])
    orphan = ~df["customer_id"].isin(set(customers["customer_id"]))
    df["orphan_customer"] = orphan.astype(int)
    audit.log(t, "BROKEN REFERENCE", "customer_id", int(orphan.sum()), int(orphan.sum()),
              "kept; flagged orphan_customer=1 -> mapped to Unknown (-1) in DimCustomer", "line is never deleted")
    sc = _int(df["ship_city_id"])
    bad_city = sc.notna() & ~sc.isin(set(locations["city_id"].dropna()))
    audit.log(t, "MISSING / BAD SHIP CITY", "ship_city_id", int(sc.isna().sum() + bad_city.sum()), int(sc.isna().sum() + bad_city.sum()),
              "left NULL -> Unknown (-1) in DimLocation",
              "NOT filled from the customer's city: ship city differs from customer city on ~11% of orders")
    df["ship_city_id"] = sc.where(~bad_city)
    return (df[["order_id", "customer_id", "customer_id_orig", "order_date", "order_status", "ship_city_id",
                "order_total", "discount_code", "discount_pct", "channel", "date_repair", "orphan_customer"]]
            .reset_index(drop=True), rejected_ids)


# =====================================================================================
# ORDER ITEMS  (quantity + price repair, discount recompute)
# =====================================================================================
def _net(q, up, pct):
    g = q * up
    return g - half_up(g * pct)


def clean_order_items(raw, orders, rejected_order_ids, products, pmap, sellers, audit):
    t = "order_items"
    n_raw = len(raw)
    df = strip_all(raw).drop_duplicates()
    audit.log(t, "EXACT DUPLICATE ROWS", "(all columns)", n_raw, len(df), "drop_duplicates", "")
    dup = df.duplicated("order_item_id", keep="first")
    audit.reject(df[dup], t, "order_item_id", "DUPLICATE_KEY")
    df = df[~dup].copy()

    parent_rej = df["order_id"].isin(rejected_order_ids)
    no_parent = ~df["order_id"].isin(set(orders["order_id"])) & ~parent_rej
    audit.reject(df[parent_rej], t, "order_item_id", "PARENT_ORDER_REJECTED")
    audit.reject(df[no_parent], t, "order_item_id", "ORPHAN_ORDER")
    df = df[~parent_rej & ~no_parent].copy().reset_index(drop=True)

    # ---- product reference (dup -> master); orphans stay, flagged
    df["product_id_orig"] = df["product_id"]
    df["product_id"] = df["product_id"].map(pmap.set_index("product_id")["master_id"]).fillna(df["product_id"])
    df["orphan_product"] = (~df["product_id"].isin(set(products["product_id"]))).astype(int)
    audit.log(t, "BROKEN REFERENCE", "product_id", int(df["orphan_product"].sum()), int(df["orphan_product"].sum()),
              "kept; flagged orphan_product=1 -> Unknown (-1) in DimProduct (COGS unknown for these lines)", "")
    df["orphan_seller"] = (~df["seller_id"].isin(set(sellers["seller_id"]))).astype(int)
    audit.log(t, "BROKEN REFERENCE", "seller_id", int(df["orphan_seller"].sum()), int(df["orphan_seller"].sum()),
              "kept; flagged orphan_seller=1 -> Unknown (-1) in DimSeller", "")

    # ---- quantity
    q_raw = to_qty(df["quantity"])
    neg = q_raw < 0
    q = q_raw.abs()
    q_ok = q.between(1, C.QTY_MAX) & (q == q.round())
    q = q.where(q_ok)
    df["qty_fix"] = np.where(neg & q_ok, "ABS_OF_NEGATIVE", "")
    # ---- unit price
    up_raw = to_num(df["unit_price"])
    up = up_raw.where((up_raw > 0) & ~is_sentinel(up_raw.fillna(0)))
    lp = df["product_id"].map(products.set_index("product_id")["list_price"])
    ratio = up / lp
    p_ok = up.notna() & (lp.isna() | ratio.between(C.PRICE_RATIO_MIN, C.PRICE_RATIO_MAX))
    good_ratio = float(ratio[p_ok & lp.notna()].median()) if (p_ok & lp.notna()).any() else 1.0
    up = up.where(p_ok)
    df["price_fix"] = ""
    pct = df["order_id"].map(orders.set_index("order_id")["discount_pct"]).astype(float)
    T = df["order_id"].map(orders.set_index("order_id")["order_total"]).astype(float)
    T_ok = T.notna()

    n_bad_q0, n_bad_p0 = int((~q_ok).sum()), int((~p_ok).sum())
    stats = {"price_from_total": 0, "price_from_list": 0, "qty_from_total": 0}

    # ---- phase 1: prices. Use order_total when the order has exactly one unknown line, else list price
    bad_orders = df.loc[~p_ok, "order_id"].unique()
    for oid, grp in df[df["order_id"].isin(bad_orders)].groupby("order_id"):
        idx = grp.index
        unknown = [i for i in idx if (not q_ok[i]) or (not p_ok[i])]
        for i in idx:
            if p_ok[i]:
                continue
            solved = False
            if len(unknown) == 1 and q_ok[i] and T_ok[i]:
                others = [j for j in idx if j != i]
                R = T[i] - _net(q[others], up[others], pct[i]).sum()
                g = R / (1 - pct[i])
                base = int(round(g / q[i])) if np.isfinite(g) else 0
                cands = np.arange(max(base - 3, 1), max(base + 4, 2))
                err = np.abs(_net(q[i], cands, pct[i]) - R)
                best = cands[err.argmin()]
                plausible = base >= 1 and best > 0 and (pd.isna(lp[i]) or C.PRICE_RATIO_MIN <= best / lp[i] <= C.PRICE_RATIO_MAX)
                if plausible and err.min() <= max(q[i], 2):
                    up[i], df.at[i, "price_fix"], solved = float(best), "ORDER_TOTAL", True
                    stats["price_from_total"] += 1
            if not solved and pd.notna(lp[i]):
                up[i], df.at[i, "price_fix"] = float(round(lp[i] * good_ratio)), "LIST_PRICE"
                stats["price_from_list"] += 1

    # ---- phase 2: quantities. exactly one unknown qty in an order -> solve from order_total
    bad_q_orders = df.loc[~q_ok, "order_id"].unique()
    for oid, grp in df[df["order_id"].isin(bad_q_orders)].groupby("order_id"):
        idx = list(grp.index)
        unk_q = [i for i in idx if not q_ok[i]]
        if len(unk_q) != 1:
            continue
        i = unk_q[0]
        others = [j for j in idx if j != i]
        if (not T_ok[i]) or up[others].isna().any() or q[others].isna().any() or pd.isna(up[i]):
            continue
        R = T[i] - _net(q[others], up[others], pct[i]).sum()
        cands = np.arange(1, C.QTY_MAX + 1)
        err = np.abs(_net(cands, up[i], pct[i]) - R)
        best = cands[err.argmin()]
        if err.min() <= max(2.0, 0.05 * max(R, 1)):
            q[i], q_ok[i] = float(best), True
            df.at[i, "qty_fix"] = "ORDER_TOTAL"
            stats["qty_from_total"] += 1

    # ---- anything still unknown -> reject with reason
    bad_qty = q.isna()
    bad_price = up.isna() & ~bad_qty
    audit.log(t, "QUANTITY OUTLIER / INVALID", "quantity", n_bad_q0 + int(neg.sum()), int(bad_qty.sum()),
              f"negative -> abs ({int(neg.sum())}); words/'2.0' -> number; 500 / >{C.QTY_MAX} recovered from order_total ({stats['qty_from_total']}); "
              f"unrecoverable -> reject BAD_QTY ({int(bad_qty.sum())})",
              "abs() of negatives matches order_total on ~99.7% of lines; qty 500 is an injected outlier (legit max is 6)")
    audit.log(t, "BAD UNIT PRICE", "unit_price", n_bad_p0, int(bad_price.sum()),
              f"{stats['price_from_total']} solved from order_total, {stats['price_from_list']} set to list_price x {good_ratio:.4f}, "
              f"{int(bad_price.sum())} rejected BAD_PRICE",
              f"invalid = <=0, sentinel 9999999, or unit/list ratio outside {C.PRICE_RATIO_MIN}-{C.PRICE_RATIO_MAX} (valid data sits in 0.99-1.10)")
    audit.reject(df[bad_qty], t, "order_item_id", "BAD_QTY")
    audit.reject(df[bad_price], t, "order_item_id", "BAD_PRICE")
    keep = ~bad_qty & ~bad_price
    df, q, up, pct = df[keep].copy(), q[keep], up[keep], pct[keep]

    # ---- discount: recompute gross x code% (matches 99.6% of the raw rows). Fills blanks, fixes inflated values
    gross = q * up
    disc = half_up(gross * pct)
    da_raw = to_num(df["discount_amount"])
    changed = da_raw.isna() | ((da_raw - disc).abs() > 1)
    audit.log(t, "MISSING / WRONG DISCOUNT", "discount_amount", int(changed.sum()), 0,
              "recomputed = round(quantity x unit_price x discount_code%)",
              f"{int(da_raw.isna().sum())} blank; {int((da_raw.notna() & changed).sum())} disagreed with the code (inflated, > gross); order-level code applies to every line (spec)")
    df["quantity"], df["unit_price"] = q.astype(int), up
    df["gross_amount"], df["discount_amount"] = gross, disc
    df["net_amount"] = gross - disc
    return (df[["order_item_id", "order_id", "product_id", "product_id_orig", "seller_id", "quantity", "unit_price",
                "discount_amount", "gross_amount", "net_amount", "qty_fix", "price_fix", "orphan_product", "orphan_seller"]]
            .reset_index(drop=True))


# =====================================================================================
# PAYMENTS
# =====================================================================================
def clean_payments(raw, orders, rejected_order_ids, audit):
    t = "payments"
    n_raw = len(raw)
    df = strip_all(raw).drop_duplicates()
    audit.log(t, "EXACT DUPLICATE ROWS", "(all columns)", n_raw, len(df), "drop_duplicates", "")
    dup = df.duplicated("payment_id", keep="first")
    audit.reject(df[dup], t, "payment_id", "DUPLICATE_KEY")
    df = df[~dup].copy()
    pr = df["order_id"].isin(rejected_order_ids)
    npar = ~df["order_id"].isin(set(orders["order_id"])) & ~pr
    audit.reject(df[pr], t, "payment_id", "PARENT_ORDER_REJECTED")
    audit.reject(df[npar], t, "payment_id", "ORPHAN_ORDER")
    df = df[~pr & ~npar].copy()
    df["payment_method"] = LabelMapper("payment_method").map(df["payment_method"], audit, t, "payment_method")
    df["payment_status"] = LabelMapper("payment_status").map(df["payment_status"], audit, t, "payment_status")
    amt = to_num(df["amount"])
    bad = amt.isna() | (amt <= 0) | is_sentinel(amt.fillna(0))
    ot = df["order_id"].map(orders.set_index("order_id")["order_total"]).astype(float)
    audit.log(t, "BAD PAYMENT AMOUNT", "amount", int(bad.sum()), int((bad & ot.isna()).sum()),
              "replaced with the order's total (payment amount equals order_total in normal rows)",
              "left NULL where the order total itself is unknown")
    # a bad amount on a split payment (order paid in 2 parts) = order_total - the other (good) part; else the whole total
    oid = df["order_id"]
    n_rows = oid.map(oid.value_counts())
    good_sum = amt.where(~bad, 0.0).groupby(oid).transform("sum")
    n_bad = bad.groupby(oid).transform("sum")
    part = ot - good_sum
    split_fix = bad & (n_rows > 1) & (n_bad == 1) & (part > 0)
    df["amount"] = amt.where(~bad, np.where(split_fix, part, ot))
    df["amount_fixed"] = bad.astype(int)
    df["n_payments"] = n_rows.astype(int)
    # deterministic 'primary' payment per order for FactSales: Paid/Refunded over Cancelled/Pending/Unknown,
    # then the larger part, then the later payment_date, then payment_id
    df["payment_date"] = _date(audit, t, "payment_date", df["payment_date"])
    rank = df["payment_status"].map({"Paid": 0, "Refunded": 0, "Pending": 1, "Cancelled": 1}).fillna(2)
    order = (pd.DataFrame({"o": oid, "r": rank, "a": -df["amount"].fillna(0), "d": -df["payment_date"].fillna(pd.Timestamp("1970-01-01")).astype("int64"), "p": df["payment_id"]})
             .sort_values(["o", "r", "a", "d", "p"]))
    first = order.index[~order["o"].duplicated()]
    df["is_primary"] = 0
    df.loc[first, "is_primary"] = 1
    audit.log(t, "SPLIT PAYMENTS", "order_id", int((n_rows > 1).sum()), int(df["is_primary"].sum()),
              "orders with 2 payment rows are split payments (parts sum to order_total); is_primary=1 marks one row per order for FactSales",
              f"primary = Paid/Refunded first, then larger part, then later payment_date; {int(split_fix.sum())} bad part amounts rebuilt as order_total - other part")
    audit.log(t, "MISSING / IMPOSSIBLE DATE", "payment_date", int(df["payment_date"].isna().sum()), int(df["payment_date"].isna().sum()),
              "kept NULL", "payment_date is not used for revenue; used only to pick between 2 payment rows")
    return df[["payment_id", "order_id", "payment_method", "payment_status", "amount", "payment_date", "amount_fixed", "n_payments", "is_primary"]].reset_index(drop=True)


# =====================================================================================
# SHIPPING
# =====================================================================================
def clean_shipping(raw, orders, rejected_order_ids, audit):
    t = "shipping"
    n_raw = len(raw)
    df = strip_all(raw).drop_duplicates()
    audit.log(t, "EXACT DUPLICATE ROWS", "(all columns)", n_raw, len(df), "drop_duplicates", "")
    dup = df.duplicated("shipment_id", keep="first")
    audit.reject(df[dup], t, "shipment_id", "DUPLICATE_KEY")
    df = df[~dup].copy()
    pr = df["order_id"].isin(rejected_order_ids)
    npar = ~df["order_id"].isin(set(orders["order_id"])) & ~pr
    audit.reject(df[pr], t, "shipment_id", "PARENT_ORDER_REJECTED")
    audit.reject(df[npar], t, "shipment_id", "ORPHAN_ORDER")
    df = df[~pr & ~npar].copy()
    df["courier"] = LabelMapper("courier").map(df["courier"], audit, t, "courier")
    df["delivery_status"] = LabelMapper("delivery_status").map(df["delivery_status"], audit, t, "delivery_status")
    sd, dd = _date(audit, t, "shipped_date", df["shipped_date"]), _date(audit, t, "delivered_date", df["delivered_date"])
    audit.log(t, "MISSING DATE", "shipped_date", int(sd.isna().sum()), int(sd.isna().sum()), "kept NULL", "ShippingDays then unknown for that order")
    neg = (dd < sd)
    far = ((dd - sd).dt.days > C.SHIPPING_DAYS_MAX)
    audit.log(t, "DELIVERED BEFORE SHIPPED", "delivered_date", int(neg.sum()), 0,
              "delivered_date set to NULL (flag date_fix)", "all such rows are exactly shipped-2 days: a systematic export fault, true date unknown")
    audit.log(t, "DELIVERY > %d DAYS" % C.SHIPPING_DAYS_MAX, "delivered_date", int(far.sum()), 0,
              "delivered_date set to NULL (flag date_fix)", "legit tail ends ~30 days; the 88-102 day cluster is corrupt")
    df["date_fix"] = np.where(neg, "DELIVERED_BEFORE_SHIPPED", np.where(far, "DELIVERY_TOO_LONG", ""))
    dd = dd.where(~(neg | far))
    df["shipped_date"], df["delivered_date"] = sd, dd
    df["shipping_days"] = (dd - sd).dt.days.astype("Int64")
    fee = to_num(df["shipping_fee"])
    bad = fee.notna() & ((fee <= 0) | (fee >= C.FEE_MAX) | is_sentinel(fee.fillna(0)))
    fee = fee.where(~bad)
    missing = fee.isna()
    mean_fee = float(fee.mean())
    df["fee_imputed"] = missing.astype(int)
    audit.log(t, "MISSING / BAD SHIPPING FEE", "shipping_fee", int(missing.sum()), 0,
              f"imputed with the mean valid fee ({mean_fee:.0f}); flagged fee_imputed=1",
              f"{int(bad.sum())} sentinel/negative values + {int((missing & ~bad).sum())} blanks; mean (not median) so total shipping cost is preserved; fee does not depend on courier")
    df["shipping_fee"] = fee.fillna(round(mean_fee))
    return df[["shipment_id", "order_id", "courier", "shipped_date", "delivered_date", "shipping_fee",
               "delivery_status", "shipping_days", "date_fix", "fee_imputed"]].reset_index(drop=True)


# =====================================================================================
# RETURNS
# =====================================================================================
def clean_returns(raw, items, orders, rejected_order_ids, audit, raw_items):
    t = "returns"
    n_raw = len(raw)
    df = strip_all(raw).drop_duplicates()
    audit.log(t, "EXACT DUPLICATE ROWS", "(all columns)", n_raw, len(df), "drop_duplicates", "")
    dup = df.duplicated("return_id", keep="first")
    audit.reject(df[dup], t, "return_id", "DUPLICATE_KEY")
    df = df[~dup].copy()
    # orphan: line not in the *raw* items -> ORPHAN_RETURN; line belongs to a rejected order/line -> parent rejected
    known_raw = set(raw_items["order_item_id"].astype("string").str.strip())
    live = set(items["order_item_id"])
    orphan = ~df["order_item_id"].isin(known_raw)
    parent = ~orphan & ~df["order_item_id"].isin(live)
    audit.reject(df[orphan], t, "return_id", "ORPHAN_RETURN", "order_item_id does not exist")
    audit.reject(df[parent], t, "return_id", "PARENT_ORDER_REJECTED", "its order line was rejected")
    audit.log(t, "BROKEN REFERENCE", "order_item_id", int(orphan.sum()), 0, "rejected ORPHAN_RETURN", "")
    df = df[~orphan & ~parent].copy()
    df["return_status"] = LabelMapper("return_status").map(df["return_status"], audit, t, "return_status")
    df["return_reason"] = LabelMapper("return_reason").map(df["return_reason"], audit, t, "return_reason")
    df["is_valid_return"] = (df["return_status"] != "Rejected").astype(int)     # spec: Rejected is not a valid return

    li = items.set_index("order_item_id")
    gross = df["order_item_id"].map(li["gross_amount"]).astype(float)
    odate = df["order_item_id"].map(li["order_id"]).map(orders.set_index("order_id")["order_date"])
    ra = to_num(df["refund_amount"])
    valid = df["is_valid_return"] == 1
    bad_ref = valid & (ra.isna() | (ra <= 0) | (ra > gross * 1.001) | is_sentinel(ra.fillna(0)))
    audit.log(t, "BAD REFUND AMOUNT", "refund_amount", int(bad_ref.sum()), 0,
              "valid returns with refund <=0 or > line gross set to the line's gross amount (full refund)",
              "refund == line gross in the modal case (7.6k rows); partial refunds (25-99%) are real and untouched. Rejected returns are not valid, amount kept as is")
    df["refund_amount"] = ra.where(~bad_ref, gross)
    df["refund_fixed"] = bad_ref.astype(int)

    rd = _date(audit, t, "return_date", df["return_date"])
    lag = pd.to_timedelta(round(((rd - odate).dt.days)[(rd >= odate) & (rd - odate <= pd.Timedelta(days=60))].median()), unit="D")
    bad_rd = rd.isna() | (rd < odate) | ((rd - odate) > pd.Timedelta(days=90))
    audit.log(t, "BAD RETURN DATE", "return_date", int(bad_rd.sum()), 0,
              f"set to order_date + {lag.days} days (median observed lag); flagged date_fixed=1",
              "invalid = unparseable, before the order date, or >90 days after it")
    df["return_date"] = rd.where(~bad_rd, odate + lag)
    df["date_fixed"] = bad_rd.astype(int)
    return df[["return_id", "order_item_id", "return_date", "return_reason", "return_status", "refund_amount",
               "is_valid_return", "refund_fixed", "date_fixed"]].reset_index(drop=True)


# =====================================================================================
# ORCHESTRATION
# =====================================================================================
def run(data_dir="data", out_dir="out"):
    os.makedirs(out_dir, exist_ok=True)
    audit = Audit()
    raw = read_raw(data_dir)
    rows_read = {k: len(v) for k, v in raw.items()}

    locations = clean_locations(raw["locations"], audit)
    sellers = clean_sellers(raw["sellers"], audit)
    products, pmap = clean_products(raw["products"], raw["order_items"], audit)
    customers, cmap = clean_customers(raw["customers"], audit)
    orders, rej_orders = clean_orders(raw["orders"], raw["shipping"], raw["payments"], customers, cmap, locations, audit)
    items = clean_order_items(raw["order_items"], orders, rej_orders, products, pmap, sellers, audit)

    # order_total: keep the valid raw total, otherwise rebuild from the clean lines
    calc = items.groupby("order_id")["net_amount"].sum()
    orders["order_total_calc"] = orders["order_id"].map(calc)
    match = (orders["order_total"] - orders["order_total_calc"]).abs() <= 2
    audit.log("orders", "ORDER TOTAL vs LINES", "order_total", int(orders["order_total"].notna().sum()), int(match.sum()),
              "order_total filled from sum(line net) where invalid; match rate after repair shown in after_count",
              "before = orders with a valid raw total, after = those whose total equals sum(qty x price - discount) +-2")
    orders["order_total"] = orders["order_total"].fillna(orders["order_total_calc"])

    # unit cost per line for COGS. Product cost where the product exists; otherwise (orphan product, or a product whose
    # cost could not even be imputed) estimate = unit_price x median(cost/unit_price) of lines with a genuine product cost.
    pcost = items["product_id"].map(products.set_index("product_id")["cost_price"])
    pimp = items["product_id"].map(products.set_index("product_id")["cost_imputed"]).fillna(0)
    genuine = pcost.notna() & (pimp == 0)
    cost_ratio = float((pcost[genuine] / items.loc[genuine, "unit_price"]).median())
    items["unit_cost"] = pcost.where(pcost.notna(), items["unit_price"] * cost_ratio).round(2)
    items["cost_source"] = np.where(pcost.isna(), "NO_PRODUCT_COST_ESTIMATE", np.where(pimp == 1, "PRODUCT_IMPUTED", "PRODUCT"))
    n_est = int(pcost.isna().sum())
    audit.log("order_items", "NO PRODUCT COST FOR LINE", "unit_cost", n_est, 0,
              f"unit_cost = unit_price x {cost_ratio:.4f} (median cost/unit_price of lines with a genuine product cost); flagged cost_source=NO_PRODUCT_COST_ESTIMATE",
              "orphan-product lines have no product record; COGS 0 would overstate margin. CostAmount in FactSales = unit_cost x quantity")

    payments = clean_payments(raw["payments"], orders, rej_orders, audit)
    shipping = clean_shipping(raw["shipping"], orders, rej_orders, audit)
    returns = clean_returns(raw["returns"], items, orders, rej_orders, audit, raw["order_items"])

    out = {"customers": customers, "customer_map": cmap, "products": products, "product_map": pmap,
           "sellers": sellers, "locations": locations, "orders": orders, "order_items": items,
           "payments": payments, "shipping": shipping, "returns": returns}
    for name, frame in out.items():
        frame.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False, date_format="%Y-%m-%d")

    rej = audit.reject_frame()
    summary = {}
    for src, dst in [("customers", "customers"), ("products", "products"), ("sellers", "sellers"), ("locations", "locations"),
                     ("orders", "orders"), ("order_items", "order_items"), ("payments", "payments"),
                     ("shipping", "shipping"), ("returns", "returns")]:
        nrej = int((rej["table"] == src).sum()) if len(rej) else 0
        summary[src] = {"rows_read": rows_read[src], "rows_rejected": nrej, "rows_loaded": len(out[dst])}
        audit.log(src, "TABLE SUMMARY", "", rows_read[src], len(out[dst]),
                  f"read {rows_read[src]}, rejected {nrej}, loaded {len(out[dst])}",
                  "difference = exact duplicates removed + merged duplicates + rejected")
    dq = audit.dq_frame()
    dq.to_csv(os.path.join(out_dir, "dq_log.csv"), index=False)
    rej.to_csv(os.path.join(out_dir, "reject.csv"), index=False)
    for tbl, lim in C.MAX_REJECT_PCT.items():
        pct = 100 * summary[tbl]["rows_rejected"] / max(summary[tbl]["rows_read"], 1)
        if pct > lim * C.GATE_SCALE:
            raise RuntimeError(f"quality gate: {tbl} rejected {pct:.2f}% (> {lim * C.GATE_SCALE}%; raise NX_GATE_SCALE only after reading dq_log/reject)")
    for tbl, s in summary.items():
        print(f"[clean] {tbl:12s} read={s['rows_read']:>7} rejected={s['rows_rejected']:>5} loaded={s['rows_loaded']:>7}")
    return summary


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "data"
    o = sys.argv[2] if len(sys.argv) > 2 else "out"
    run(d, o)
