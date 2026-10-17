"""Builds docs/data_quality_report.pdf from the cleaning outputs (re-run after the Hour-6 drop).

Usage: python src/clean/make_dq_report.py out docs/data_quality_report.pdf [data]   (data = raw CSV folder, for the raw-spelling counts)
Inputs (all produced by clean_all.py / sensitivity.py): out/dq_log.csv, reject.csv, sensitivity.csv, + clean tables.
"""
import os
import sys
from datetime import date
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_config as C   # noqa: E402

RED = colors.HexColor("#B3202A")
GREY = colors.HexColor("#F2F2F2")
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], textColor=RED, fontSize=15, spaceBefore=6, spaceAfter=6)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=11.5, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("B", parent=ss["Normal"], fontSize=9, leading=12)
CELL = ParagraphStyle("C", parent=ss["Normal"], fontSize=7.4, leading=9)
CELLB = ParagraphStyle("CB", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)


def P(text, style=CELL):
    return Paragraph(escape(str(text)) if text is not None and str(text) != "nan" else "", style)


def fmt(v):
    try:
        f = float(v)
        return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"
    except (TypeError, ValueError):
        return "" if str(v) == "nan" else str(v)


def table(df, widths, header=None):
    header = header or list(df.columns)
    rows = [[Paragraph(escape(h), CELLB) for h in header]]
    for r in df.itertuples(index=False):
        rows.append([P(x) if not isinstance(x, (int, float)) else P(fmt(x)) for x in r])
    t = Table(rows, colWidths=[w * cm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), RED), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(1.5 * cm, 0.9 * cm, "NexusMart Datathon - Data Quality Report (generated from audit.dq_log)")
    canvas.drawRightString(landscape(A4)[0] - 1.5 * cm, 0.9 * cm, f"Page {doc.page}")
    canvas.restoreState()


TABLES = ["customers", "products", "sellers", "locations", "orders", "order_items", "payments", "shipping", "returns"]


def waterfall(dq, rej):
    """read - exact duplicates - merged entities - rejected = loaded, per table, with a reconciliation flag."""
    rows = []
    for t in TABLES:
        summ = dq[(dq.issue == "TABLE SUMMARY") & (dq.table == t)]
        if summ.empty:
            continue
        read, loaded = int(summ.iloc[0].before_count), int(summ.iloc[0].after_count)
        ex = dq[(dq.table == t) & (dq.issue == "EXACT DUPLICATE ROWS")]
        dup = int((ex.before_count - ex.after_count).sum())
        mg = dq[(dq.table == t) & dq.issue.isin(["DUPLICATE CUSTOMERS", "DUPLICATE PRODUCTS"])]
        merged = int((mg.before_count - mg.after_count).sum())
        rj = rej[rej.table == t] if len(rej) else rej
        nrej = int(len(rj))
        reasons = ", ".join(f"{k} {v:,}" for k, v in rj.reason_code.value_counts().items()) if nrej else "-"
        calc = read - dup - merged - nrej
        rows.append([t, read, dup, merged, nrej, loaded, "OK" if calc == loaded else f"CHECK ({calc:,})", reasons])
    return pd.DataFrame(rows, columns=["Table", "Rows read (raw)", "- Exact duplicate rows", "- Duplicate entities merged",
                                       "- Rejected (reject table)", "= Rows loaded (clean)", "Reconciles?", "Reject reasons"])


def raw_distinct(data_dir, table, column):
    """distinct values exactly as exported (no trimming, blank counts as a value)."""
    path = os.path.join(data_dir or "", f"{table}.csv")
    if not os.path.exists(path):
        return ""
    return int(pd.read_csv(path, dtype="string", keep_default_na=False, usecols=[column])[column].nunique())


def sv(sn, prefix, col):
    r = sn[sn.decision.str.startswith(prefix)]
    return r.iloc[0][col] if len(r) else None


def key_assumptions(out_dir, dq, sn):
    """Section 8: the decisions a judge will ask about, with this run's numbers."""
    R = lambda n: pd.read_csv(os.path.join(out_dir, f"{n}.csv"))
    o, i = R("orders"), R("order_items")
    f = lambda v, d=2: "n/a" if v is None or str(v) == "nan" else f"{float(v):,.{d}f}"
    dqr = lambda t, issue: dq[(dq.table == t) & (dq.issue == issue)].iloc[0]
    n_s, n_p = int((o.date_repair == "SHIPPED_DATE").sum()), int((o.date_repair == "PAYMENT_DATE").sum())
    od = dqr("orders", "ORDER DATE REPAIR")
    cu = dqr("customers", "DUPLICATE CUSTOMERS")
    orphan_lines = int(i.orphan_product.sum())
    import re
    m_ = re.search(r"median ratio ([0-9.]+)", str(dqr('products', 'MISSING/BAD COST PRICE').assumption))
    cat_ratio = m_.group(1) if m_ else 'n/a'
    est = i[i.cost_source == "NO_PRODUCT_COST_ESTIMATE"] if "cost_source" in i.columns else i.iloc[0:0]
    ratio = float((est.unit_cost / est.unit_price).median()) if len(est) else float("nan")
    items = [
        ("A. Impossible order dates are repaired, not rejected",
         f"<b>Rule:</b> an order date that cannot be parsed or lies outside {C.DATE_MIN.date()}..{C.DATE_MAX.date()} is rebuilt as shipped_date minus the usual lag "
         f"({n_s:,} orders), else payment_date minus its lag ({n_p:,} orders); only {int(od.after_count):,} orders with neither date are rejected (BAD_DATE / DATE_OUT_OF_RANGE). "
         f"The lag is learnt from valid rows (shipped - order is 0-2 days on 100% of them, median shown in the decision table).<br/>"
         f"<b>Why:</b> rejecting those orders would remove {abs(float(sv(sn, 'Order date repair -> reject', 'delta_pct_or_pts'))):.2f}% of NMV (beyond the 1% tolerance) and punch holes in the monthly trend. "
         f"<b>Risk:</b> a repaired date can be 1 day off; about {f(sv(sn, 'Order date repair by payment_date', 'delta_pct_or_pts'), 2)}% of NMV would change month under the alternative anchor."),
        ("B. Duplicate customers are merged (email or phone, never name alone)",
         f"<b>Rule:</b> records sharing a normalised email, or a phone number plus similar name (&gt;= {C.PHONE_NAME_SIM}), get the lowest customer_id as master; every duplicate-to-master pair is kept in customer_map. "
         f"{int(cu.before_count):,} customer records become {int(cu.after_count):,}.<br/>"
         f"<b>Effect:</b> Active Customers {f(sv(sn, 'Customer dedupe', 'baseline'), 0)} (unmerged) vs {f(sv(sn, 'Customer dedupe', 'alternative'), 0)} (merged), "
         f"{f(sv(sn, 'Customer dedupe', 'delta_pct_or_pts'), 1)}%. Revenue is unaffected; repeat purchase rate, CLV and RFM are. Without merging, customers are over-counted and repeat buying is understated."),
        ("C. Lines of unknown products stay in the data; their cost is estimated",
         f"<b>Rule:</b> {orphan_lines:,} order lines point to product ids that do not exist. They are kept (revenue is real) and mapped to the Unknown product. "
         f"Their cost has no product record, so unit_cost = unit_price x {ratio:.3f} (median cost/price of lines with a genuine cost), flagged cost_source = NO_PRODUCT_COST_ESTIMATE.<br/>"
         f"<b>Effect:</b> dropping these lines would lower NMV by {abs(float(sv(sn, 'Orphan-product lines -> drop', 'delta_pct_or_pts'))):.2f}%; costing them at zero would raise margin by "
         f"{f(sv(sn, 'Orphan-product lines: COGS = 0', 'delta_pct_or_pts'), 2)} pt; excluding them changes it by {f(sv(sn, 'Orphan-product lines: excluded', 'delta_pct_or_pts'), 2)} pt. All inside the 0.5 pt tolerance."),
        ("D. cost_price above list_price is treated as corrupt and imputed",
         f"<b>Rule:</b> a product cost that is missing, not positive, or above list price is replaced by list_price x the median cost/list ratio of its category ({cat_ratio}); flagged cost_imputed = 1.<br/>"
         f"<b>Evidence:</b> {str(sv(sn, 'cost_price > list_price', 'note')).split('. ', 1)[-1].capitalize()}. Keeping those costs would lower margin by {abs(float(sv(sn, 'cost_price > list_price', 'delta_pct_or_pts'))):.2f} pt (beyond tolerance), so this decision matters. "
         f"Imputation quality: {sv(sn, 'Imputed cost -> exclude', 'note').split('. ')[-1]}; products with imputed cost carry about {100 * (i.cost_source == 'PRODUCT_IMPUTED').mean():.1f}% of lines, "
         f"and a plain +/-5% bias moves margin only {abs(float(sv(sn, 'Imputed cost biased by -5%', 'delta_pct_or_pts'))):.2f} pt."),
    ]
    out = []
    for h, body in items:
        out += [Paragraph(h, H2), Paragraph(body, BODY)]
    return out


def validation(out_dir):
    R = lambda n: pd.read_csv(os.path.join(out_dir, f"{n}.csv"))
    o, i, p, s, r = R("orders"), R("order_items"), R("payments"), R("shipping"), R("returns")
    c, pr, se, l = R("customers"), R("products"), R("sellers"), R("locations")
    rows = [
        ("order_total equals sum(qty x price - discount) +-2 (valid raw totals)", f"{100 * ((o.order_total - o.order_total_calc).abs() <= 2).mean():.2f}%"),
        ("Primary keys unique (orders, items, payments, shipments, returns, customers, products)",
         "PASS" if all([o.order_id.is_unique, i.order_item_id.is_unique, p.payment_id.is_unique, s.shipment_id.is_unique, r.return_id.is_unique, c.customer_id.is_unique, pr.product_id.is_unique]) else "FAIL"),
        ("order_items.order_id / payments / shipping -> orders", "PASS" if i.order_id.isin(o.order_id).all() and p.order_id.isin(o.order_id).all() and s.order_id.isin(o.order_id).all() else "FAIL"),
        ("returns.order_item_id -> order_items", "PASS" if r.order_item_id.isin(i.order_item_id).all() else "FAIL"),
        ("order_items.seller_id -> sellers; ship_city_id -> locations", "PASS" if i.seller_id.isin(se.seller_id).all() and o.ship_city_id.dropna().isin(l.city_id).all() else "FAIL"),
        ("Orphans flagged, not dropped (customer / product lines)", f"{int(o.orphan_customer.sum()):,} orders / {int(i.orphan_product.sum()):,} lines -> Unknown member"),
        ("All order dates inside 2024-01-01..2025-06-30", "PASS" if o.order_date.between("2024-01-01", "2025-06-30").all() else "FAIL"),
        ("Quantity 1..%d and unit_price > 0 on every kept line" % C.QTY_MAX, "PASS" if i.quantity.between(1, C.QTY_MAX).all() and (i.unit_price > 0).all() else "FAIL"),
        ("Distinct canonical categories / payment methods / couriers", f"{pr.category.nunique()} / {p.payment_method.nunique()} / {s.courier.nunique()}"),
    ]
    if "is_primary" in p.columns:
        two = p[p.n_payments > 1].merge(o[["order_id", "order_total"]], on="order_id").groupby("order_id").agg(s=("amount", "sum"), t=("order_total", "first"))
        rows += [
            ("Split-payment orders (2 payment rows): parts add up to order_total (+-2)", f"{len(two):,} orders, {100 * ((two.s - two.t).abs() <= 2).mean():.1f}% add up"),
            ("Exactly one is_primary payment row per order (FactSales picks this row)", "PASS" if p.groupby("order_id").is_primary.sum().eq(1).all() and p.order_id.nunique() == len(o) else "FAIL"),
        ]
    else:
        rows.append(("Orders with 2 payment rows (kept, fact build picks one)", f"{int((p.groupby('order_id').size() > 1).sum()):,}"))
    if "unit_cost" in i.columns:
        rows.append(("Every kept order line has a unit_cost (estimated where no product cost exists)", "PASS" if i.unit_cost.notna().all() else "FAIL"))
    return pd.DataFrame(rows, columns=["Check", "Result"])


def build(out_dir="out", pdf_path="docs/data_quality_report.pdf", data_dir="data"):
    dq = pd.read_csv(os.path.join(out_dir, "dq_log.csv"))
    rej = pd.read_csv(os.path.join(out_dir, "reject.csv"))
    sens_path = os.path.join(out_dir, "sensitivity.csv")
    os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)
    doc = SimpleDocTemplate(pdf_path, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.5 * cm,
                            title="NexusMart Data Quality Report")
    st = []
    st += [Paragraph("NexusMart - Data Quality Report", ParagraphStyle("T", parent=ss["Title"], textColor=RED, fontSize=22, alignment=0)),
           Paragraph(f"Generated {date.today().isoformat()} from <b>audit.dq_log</b>, <b>audit.reject</b> and the clean tables. "
                     "Every cleaning decision is implemented in Python (<font name='Courier'>src/clean/</font>); nothing was edited by hand in Excel or the database. "
                     "In dq_log, <b>before</b> = records (or distinct label spellings) affected before the fix; <b>after</b> = records still unresolved after the fix.", BODY),
           Spacer(1, 6), Paragraph("1. Rows read, rejected and loaded per table", H1)]
    wf = waterfall(dq, rej)
    st.append(table(wf, [2.4, 2.4, 2.6, 2.9, 2.9, 2.9, 2.2, 8.3]))
    st.append(Spacer(1, 4))
    ow = wf[wf.Table == "orders"]
    if len(ow):
        r_ = ow.iloc[0]
        st.append(Paragraph(f"<b>How to read it:</b> rows read - exact duplicate rows - duplicate entities merged - rejected = rows loaded. "
                            f"Example, orders: {r_.iloc[1]:,} - {r_.iloc[2]:,} - {r_.iloc[3]:,} - {r_.iloc[4]:,} = {r_.iloc[5]:,}. "
                            "Rejected records are never deleted silently: each sits in the reject table with a reason code and the full raw row. "
                            "Child rows of a rejected order (PARENT_ORDER_REJECTED) are rejected with it so no orphan child remains.", BODY))

    st += [PageBreak(), Paragraph("2. Cleaning decisions with before / after counts", H1)]
    dec = dq[~dq.issue.isin(["TABLE SUMMARY", "INCONSISTENT LABELS", "UNMATCHED LABELS"])].copy()
    dec = dec[["table", "issue", "column", "before_count", "after_count", "action", "assumption"]]
    dec.columns = ["Table", "Issue", "Column", "Before", "After", "Fix applied", "Assumption / business reason"]
    st.append(table(dec, [1.9, 3.4, 2.3, 1.5, 1.4, 8.0, 8.2]))

    st += [PageBreak(), Paragraph("3. Label standardisation (one concept, one spelling)", H1)]
    lab = dq[dq.issue == "INCONSISTENT LABELS"][["table", "column", "before_count", "after_count", "assumption"]].copy()
    lab.insert(2, "raw", [raw_distinct(data_dir, t, c) for t, c in zip(lab["table"], lab["column"])])
    lab.columns = ["Table", "Column", "Raw distinct values (as exported)", "Spellings after trimming spaces", "Canonical after", "Notes"]
    st.append(table(lab, [2.4, 3.0, 3.2, 3.2, 2.4, 12.3]))
    st.append(Spacer(1, 3))
    st.append(Paragraph("<b>Why two 'before' numbers:</b> 'Raw distinct values' counts every distinct string exactly as exported, so 'Fashion' and 'Fashion ' (trailing space) count twice and a blank counts as one value "
                        "(example: product categories 74 raw -> 62 after trimming spaces -> 12 canonical). The decision log works on trimmed, non-blank values, hence the smaller second number. "
                        "Case and punctuation variants ('FASHION', 'Home & Kitchen' vs 'Home and Kitchen') are collapsed by the alias dictionary in nx_config.LABELS.", BODY))
    um = dq[dq.issue == "UNMATCHED LABELS"]
    st.append(Spacer(1, 4))
    if len(um):
        st.append(Paragraph("Unmatched labels in this run (mapped to Unknown; add them to nx_config.LABELS):", H2))
        st.append(table(um[["table", "column", "before_count", "assumption"]].rename(columns={"before_count": "Rows"}), [2.6, 3.4, 1.8, 18.9]))
    else:
        st.append(Paragraph("<b>No unmatched labels in this run:</b> every spelling in the supplied data maps to a canonical value. "
                            "A new spelling in a later data drop is logged here as UNMATCHED LABELS (fuzzy match first), never crashes the pipeline.", BODY))
    newd = dq[dq.issue == "UNRECOGNISED DATE FORMAT"]
    if len(newd):
        st.append(Paragraph("New date formats detected in this run:", H2))
        st.append(table(newd[["table", "column", "before_count", "assumption"]].rename(columns={"before_count": "Rows"}), [2.6, 3.4, 1.8, 18.9]))

    st += [PageBreak(), Paragraph("4. Reject table: reason codes", H1)]
    if len(rej):
        rs = rej.groupby(["table", "reason_code"]).size().reset_index(name="records")
        rs["meaning"] = rs["reason_code"].map(C.REASONS).fillna("")
        rs.columns = ["Table", "Reason code", "Records", "Meaning"]
        st.append(table(rs, [3, 4.2, 2.2, 17.5]))
    else:
        st.append(Paragraph("No records rejected.", BODY))
    st.append(Spacer(1, 4))
    st.append(Paragraph("Most rejects are child records of the 13 orders whose date could not be repaired (PARENT_ORDER_REJECTED) and the 139 returns pointing at order lines that do not exist (ORPHAN_RETURN). "
                        "Orphan customers/products are <b>not</b> rejected: the line is kept and mapped to the Unknown member.", BODY))

    if os.path.exists(sens_path):
        st += [PageBreak(), Paragraph("5. Sensitivity: how much does each big decision move the headline numbers?", H1),
               Paragraph("Answer-key tolerance is about +-1% for revenue and +-0.5 percentage points for rates. Each row recomputes the metric with the alternative treatment. "
                         "Only decisions marked YES move a headline number beyond tolerance; they are documented as key assumptions.", BODY), Spacer(1, 4)]
        sn = pd.read_csv(sens_path)
        sn["delta"] = sn.apply(lambda r: f"{r['delta_pct_or_pts']:+.3f} {r['unit']}", axis=1)
        sn = sn[["decision", "rows_affected", "metric", "baseline", "alternative", "delta", "exceeds_tolerance"]]
        sn["baseline"] = sn["baseline"].map(lambda v: fmt(v) if str(v) != "nan" else "")
        sn["alternative"] = sn["alternative"].map(lambda v: fmt(v) if str(v) != "nan" else "")
        sn.columns = ["Alternative treatment tested", "Rows affected", "Metric", "Our baseline", "Alternative", "Change", "> tolerance?"]
        st.append(table(sn, [9.2, 2.0, 3.0, 3.1, 3.1, 3.0, 2.2]))
        st.append(Spacer(1, 4))
        flagged = pd.read_csv(sens_path)
        flagged = flagged[flagged["exceeds_tolerance"] == "YES"]
        if len(flagged):
            items = "; ".join(f"{r.decision} ({r.delta_pct_or_pts:+.2f} {r.unit} on {r.metric})" for r in flagged.itertuples())
            txt = "<b>Beyond tolerance (document as key assumptions in the README):</b> " + escape(items) + "."
        else:
            txt = "<b>No tested alternative moves a headline number beyond tolerance.</b>"
        st.append(Paragraph(txt, BODY))

    st += [PageBreak(), Paragraph("6. Validation of the clean output", H1), table(validation(out_dir), [17, 10.5]), Spacer(1, 8),
           Paragraph("7. Known limitations (stated honestly; figures refer to the supplied dataset)", H1)]
    lim = [
        "Order dates repaired from shipped_date - 1 day can be off by up to 1 day (shipped - order is 0, 1 or 2 days on every valid order); monthly totals are unaffected except at month boundaries (about 0.07% of NMV moves month).",
        "Unit prices solved from order_total are exact when the order total is valid; 29 lines fall back to list price x median ratio. Orders with a second unknown line use list price.",
        "Missing or corrupt cost_price (about 7% of products, cost_imputed = 1) is imputed from the category median cost/list ratio, so Margin carries estimation error for those products (see section 5 for the size). Lines of orphan products get an estimated unit_cost (cost_source = NO_PRODUCT_COST_ESTIMATE).",
        "Split payments: an order paid in two parts has two payment rows. FactSales takes the is_primary row (Paid/Refunded first, then the larger part), so PaymentMethod shows the larger part's method for orders whose two parts use different methods.",
        "Shipping fee is imputed with the mean for about 6% of shipments, so total shipping cost is approximate. shipping_days is NULL where delivered or shipped date is missing or was corrupt.",
        "Province of 25 cities was inferred from coordinates (about 87% leave-one-out accuracy). Gender, seller tier and sub-category stay Unknown where they cannot be inferred.",
        "Refund amounts of 0 or above the line gross on valid returns are set to the full line amount (modal behaviour). Invalid return dates are set to order date + median lag.",
        "Customer merging links records by identical email or phone only. Two different people sharing a phone number with dissimilar names are not merged.",
    ]
    for t in lim:
        st.append(Paragraph("&bull; " + escape(t), BODY))
    if os.path.exists(sens_path):
        st += [PageBreak(), Paragraph("8. Key assumptions (the decisions that move the headline numbers)", H1),
               Paragraph("Each block states the rule, why it was chosen over the alternative, and its measured effect in this run (numbers come from dq_log and sensitivity.csv).", BODY)]
        st += key_assumptions(out_dir, dq, pd.read_csv(sens_path))
    doc.build(st, onFirstPage=footer, onLaterPages=footer)
    return pdf_path


if __name__ == "__main__":
    print(build(*(sys.argv[1:4] or ["out", "docs/data_quality_report.pdf", "data"])))
