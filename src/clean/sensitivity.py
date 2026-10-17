"""B3 - sensitivity table: how much does each big cleaning decision move the headline numbers?

Usage: python src/clean/sensitivity.py data out      (run clean_all.py first)
Writes out/sensitivity.csv. Any decision moving NMV by > 1% (or a rate by > 0.5 pt) is flagged:
those must be written up as key assumptions in the README (answer key tolerance: revenue +-1%, rates +-0.5pt).
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from toolkit import parse_date, strip_all, to_num, to_qty   # noqa: E402


def kpis(items, orders, returns):
    st = items["order_id"].map(orders.set_index("order_id")["order_status"])
    nc = items[st != "Cancelled"]
    nmv = nc["net_amount"].sum()
    deliv = nc[st.loc[nc.index] != "In Transit"]
    valid = returns[returns["is_valid_return"] == 1]
    refunds = valid[valid["order_item_id"].isin(nc["order_item_id"])]["refund_amount"].sum()
    rr = valid["order_item_id"].isin(deliv["order_item_id"]).sum() / len(deliv)
    canc = (orders["order_status"] == "Cancelled").mean()
    out = {"NMV": nmv, "NetRevenue": nmv - refunds, "ReturnRate": rr * 100, "CancelRate": canc * 100}
    if "unit_cost" in items.columns:                       # Margin = Net revenue - COGS of kept lines (spec)
        kept = nc[~nc["order_item_id"].isin(valid["order_item_id"])]
        cogs = (kept["unit_cost"] * kept["quantity"]).sum()
        out["Margin"] = out["NetRevenue"] - cogs
        out["MarginPct"] = 100 * out["Margin"] / out["NetRevenue"]
    return out


def main(data_dir="data", out_dir="out"):
    rd = lambda n: pd.read_csv(os.path.join(out_dir, f"{n}.csv"), parse_dates=[c for c in ("order_date",) if n == "orders"])
    items, orders, returns = rd("order_items"), rd("orders"), rd("returns")
    base = kpis(items, orders, returns)
    rows = []

    def add(decision, n, alt, metric="NMV", note=""):
        b = base[metric]
        d = alt - b
        money = metric in ("NMV", "NetRevenue", "Margin")
        pct = 100 * d / b if money else d                                   # rates: percentage points
        flag = abs(pct) > (1.0 if money else 0.5)
        rows.append([decision, n, metric, round(b, 4), round(alt, 4), round(d, 4), round(pct, 4),
                     "%" if money else "pts", "YES" if flag else "no", note])

    lp = items["product_id"].map(pd.read_csv(os.path.join(out_dir, "products.csv")).set_index("product_id")["list_price"])

    # 1 price repair: drop the repaired lines instead
    m = items["price_fix"].notna()
    add("Price repair -> reject repaired lines instead", int(m.sum()), kpis(items[~m], orders, returns)["NMV"])
    # 2 price repair: list price instead of order_total
    alt = items.copy()
    mm = alt["price_fix"] == "ORDER_TOTAL"
    alt.loc[mm, "net_amount"] = (alt.loc[mm, "quantity"] * lp[mm].round()) - alt.loc[mm, "discount_amount"]
    add("Price repair -> list price instead of order_total", int(mm.sum()), kpis(alt, orders, returns)["NMV"])
    # 3 qty 500 outliers: reject instead of recovering
    m = items["qty_fix"] == "ORDER_TOTAL"
    add("Qty outlier (500) -> reject instead of recover from order_total", int(m.sum()), kpis(items[~m], orders, returns)["NMV"])
    # 4 negative qty: drop instead of abs()
    m = items["qty_fix"] == "ABS_OF_NEGATIVE"
    add("Negative qty -> drop lines instead of abs()", int(m.sum()), kpis(items[~m], orders, returns)["NMV"])
    # 5 date repair: reject repaired orders instead
    rep = orders.loc[orders["date_repair"].notna(), "order_id"]
    add("Order date repair -> reject those orders instead", len(rep), kpis(items[~items["order_id"].isin(rep)], orders, returns)["NMV"])
    # 6 discount: trust raw discount_amount (blank = 0)
    raw = strip_all(pd.read_csv(os.path.join(data_dir, "order_items.csv"), dtype="string", keep_default_na=False))
    da = raw.set_index("order_item_id")["discount_amount"].pipe(to_num)
    alt = items.copy()
    alt["net_amount"] = alt["gross_amount"] - alt["order_item_id"].map(da).fillna(0)
    add("Discount -> trust raw discount_amount (blank=0) instead of code%", int(alt["order_item_id"].map(da).isna().sum()), kpis(alt, orders, returns)["NMV"])
    # 7 orphan product lines dropped
    m = items["orphan_product"] == 1
    add("Orphan-product lines -> drop instead of Unknown member", int(m.sum()), kpis(items[~m], orders, returns)["NMV"])
    # 8 in-transit excluded (spec says include; shown for awareness)
    st = items["order_id"].map(orders.set_index("order_id")["order_status"])
    add("In Transit excluded from NMV (spec says INCLUDE)", int((st == "In Transit").sum()), kpis(items[st != "In Transit"], orders, returns)["NMV"])
    # 9 refund repair: leave raw refund amounts
    rawr = pd.read_csv(os.path.join(data_dir, "returns.csv"), dtype="string", keep_default_na=False)
    rr = returns.copy()
    rr["refund_amount"] = rr["return_id"].map(rawr.set_index("return_id")["refund_amount"].pipe(to_num)).fillna(0)
    add("Refund repair -> leave raw refund (0 / > line gross)", int(returns["refund_fixed"].sum()), kpis(items, orders, rr)["NetRevenue"], "NetRevenue")
    # 10 duplicates: cancellation rate if duplicate order rows were NOT removed
    ro = pd.read_csv(os.path.join(data_dir, "orders.csv"), dtype="string", keep_default_na=False)
    from toolkit import LabelMapper, Audit
    s = LabelMapper("order_status").map(ro["order_status"], Audit(), "orders", "order_status")
    add("Duplicate orders NOT removed (cancellation rate)", len(ro) - len(orders), (s == "Cancelled").mean() * 100, "CancelRate")
    # 11 return rate if 'Rejected' counted as valid (spec says no)
    r2 = returns.copy()
    r2["is_valid_return"] = 1
    add("Rejected returns counted as valid (spec says NOT valid)", int((returns["is_valid_return"] == 0).sum()), kpis(items, orders, r2)["ReturnRate"], "ReturnRate")
    # 12 monthly distribution: repaired orders by payment date instead of shipped date
    pay = pd.read_csv(os.path.join(out_dir, "payments.csv"), parse_dates=["payment_date"])
    pmin = pay.groupby("order_id")["payment_date"].min()
    o = orders[orders["date_repair"].notna()].copy()
    o["alt"] = o["order_id"].map(pmin)
    o = o[o["alt"].notna()]
    moved = o[o["alt"].dt.to_period("M") != o["order_date"].dt.to_period("M")]
    nmv_o = items.groupby("order_id")["net_amount"].sum()
    moved_share = nmv_o.reindex(moved["order_id"]).sum() / nmv_o.sum() * 100
    rows.append(["Order date repair by payment_date instead of shipped_date (monthly shift only; NMV total unchanged)",
                 len(moved), "NMV moved between months", "", "", "", round(moved_share, 4), "% of NMV", "no" if moved_share < 1 else "YES", ""])
    # 14-18 margin: cost imputation / cost > list / orphan cost
    pr = pd.read_csv(os.path.join(out_dir, "products.csv"))
    rawp = pd.read_csv(os.path.join(data_dir, "products.csv"), dtype="string", keep_default_na=False)
    rawcost = rawp.set_index("product_id")["cost_price"].pipe(to_num)
    imp_ids = set(pr.loc[pr["cost_imputed"] == 1, "product_id"])
    m_imp = items["product_id"].isin(imp_ids)
    mp = lambda it_: kpis(it_, orders, returns)

    def add_margin(decision, n, alt_items, note):
        k = mp(alt_items)
        rows.append([decision, n, "MarginPct", round(base["MarginPct"], 4), round(k["MarginPct"], 4), round(k["MarginPct"] - base["MarginPct"], 4),
                     round(k["MarginPct"] - base["MarginPct"], 4), "pts", "YES" if abs(k["MarginPct"] - base["MarginPct"]) > 0.5 else "no",
                     f"Margin amount {100 * (k['Margin'] - base['Margin']) / base['Margin']:+.2f}%. " + note])

    # how good is the imputation? leave-one-out style check on products that have a genuine cost
    pk = pr[pr["cost_imputed"] == 0]
    cat_med = (pk["cost_price"] / pk["list_price"]).groupby(pk["category"]).transform("median")
    err = ((pk["list_price"] * cat_med - pk["cost_price"]) / pk["cost_price"]).abs()
    errnote = f"imputation error on products with a genuine cost: median {100 * err.median():.1f}%, p90 {100 * err.quantile(.9):.1f}%"
    add_margin("Imputed cost -> exclude those products from margin instead", int(m_imp.sum()), items[~m_imp], errnote)
    for f, label, stress in ((0.95, "Imputed cost biased by -5% (about the median imputation error)", False),
                             (1.05, "Imputed cost biased by +5% (about the median imputation error)", False),
                             (0.8, "Imputed cost biased by -20% (stress test)", True),
                             (1.2, "Imputed cost biased by +20% (stress test)", True)):
        alt = items.copy()
        alt.loc[m_imp, "unit_cost"] = alt.loc[m_imp, "unit_cost"] * f
        add_margin(label, int(m_imp.sum()), alt, errnote + ("; errors are per-product and largely cancel (bias +0.7%), a systematic bias of ~10% would be needed to leave tolerance" if stress else ""))
        if stress:
            rows[-1][8] = "stress only"
    alt = items.copy()
    gt = m_imp & (alt["product_id"].map(rawcost) > alt["product_id"].map(pr.set_index("product_id")["list_price"]))
    alt.loc[gt, "unit_cost"] = alt.loc[gt, "product_id"].map(rawcost)
    rawlist = rawp.set_index("product_id")["list_price"].pipe(to_num)
    lp_clean = pr.set_index("product_id")["list_price"]
    sel = (rawcost > lp_clean.reindex(rawcost.index)) & (rawlist == lp_clean.reindex(rawlist.index))     # list price untouched by cleaning
    ratio_gt = (rawcost[sel] / lp_clean.reindex(rawcost.index)[sel]).dropna()
    add_margin("cost_price > list_price kept as valid instead of imputed", int(gt.sum()), alt,
               f"all {len(ratio_gt)} such products (list price untouched) have cost = {(f"{ratio_gt.min():.2f}" if round(ratio_gt.min(),2)==round(ratio_gt.max(),2) else f"{ratio_gt.min():.2f}-{ratio_gt.max():.2f}")} x list_price, while normal products never exceed 0.97 -> systematic corruption")
    alt = items.copy()
    o = alt["cost_source"] == "NO_PRODUCT_COST_ESTIMATE"
    alt.loc[o, "unit_cost"] = 0.0
    add_margin("Orphan-product lines: COGS = 0 instead of estimated cost", int(o.sum()), alt, "estimate = unit_price x median(cost/unit_price)")
    alt = items[~o]
    add_margin("Orphan-product lines: excluded from margin instead", int(o.sum()), alt, "")

    # 13 customer dedupe effect on active customers
    cm = pd.read_csv(os.path.join(out_dir, "customer_map.csv"))
    act = orders[orders["order_status"] != "Cancelled"]
    after = act["customer_id"].nunique()
    before = act["customer_id_orig"].nunique()
    rows.append(["Customer dedupe (active customers)", len(cm) - cm["master_id"].nunique(), "ActiveCustomers", before, after, after - before,
                 round(100 * (after - before) / before, 3), "%", "YES" if abs(after - before) / before > 0.01 else "no",
                 "affects Active Customers, repeat rate, CLV, RFM - not NMV"])
    out = pd.DataFrame(rows, columns=["decision", "rows_affected", "metric", "baseline", "alternative", "delta", "delta_pct_or_pts", "unit", "exceeds_tolerance", "note"])
    out.to_csv(os.path.join(out_dir, "sensitivity.csv"), index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80)
    print("BASELINE", {k: round(v, 3) for k, v in base.items()})
    print(out.drop(columns=["note"]).to_string(index=False))
    return out


if __name__ == "__main__":
    main(*(sys.argv[1:3] or ["data", "out"]))
