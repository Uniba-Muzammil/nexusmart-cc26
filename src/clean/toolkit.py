"""CODE//CONNECT'26 cleaning toolkit.

Generic, config-driven helpers. Nothing here hard-codes today's labels, so the
hour-6 data drop does not break it. Every helper logs to a DQ object.
"""
import re
import difflib
import numpy as np
import pandas as pd

WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten".split())}


class DQ:
    """Collects dq_log rows and rejected rows. Nothing is dropped silently."""

    def __init__(self):
        self.log_rows = []
        self.reject_frames = []

    def log(self, issue, table, column, before, after, action, affected=None):
        """before/after = counts before and after the fix (rows, or distinct
        labels for label fixes); affected = rows actually changed."""
        self.log_rows.append(dict(issue=issue, table=table, column=column,
                                  rows_before=int(before), rows_after=int(after),
                                  rows_affected=int(abs(before - after) if affected is None else affected),
                                  action=action))

    def reject(self, df, table, reason):
        if len(df):
            r = df.copy()
            r["reject_table"], r["reason_code"] = table, reason
            self.reject_frames.append(r)

    def log_df(self):
        return pd.DataFrame(self.log_rows)

    def reject_df(self):
        """Rejects stored as (table, reason, row as JSON text) so schemas can differ."""
        if not self.reject_frames:
            return pd.DataFrame(columns=["reject_table", "reason_code", "row_data"])
        out = []
        for f in self.reject_frames:
            meta = f[["reject_table", "reason_code"]]
            data = f.drop(columns=["reject_table", "reason_code"]).astype(str)
            out.append(meta.assign(row_data=data.apply(lambda r: r.to_json(), axis=1)))
        return pd.concat(out, ignore_index=True)


# ---------- dates ----------
def parse_dates(s):
    """Parses 2024-01-31, 31/01/2024 (day first) and 'Nov 23 2024'.
    Impossible dates (30 Feb, month 13, 00/00/2024) become NaT."""
    s = s.astype("string").str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%b %d %Y", "%B %d %Y"):
        todo = out.isna() & s.notna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


# ---------- numbers ----------
def to_number(s, sentinels=(9999999, 99999999)):
    """'Rs. 2,290' -> 2290, 'two' -> 2, '1.0' -> 1. Sentinels -> NaN."""
    def one(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        t = str(v).strip().lower()
        if t in WORDS:
            return float(WORDS[t])
        t = re.sub(r"\brs\.?|\bpkr\b", "", t.replace(",", ""))   # 'Rs. 2,290': drop the 'Rs.' dot first
        t = re.sub(r"[^\d.\-]", "", t)
        try:
            return float(t)
        except ValueError:
            return np.nan
    n = s.map(one)
    return n.mask(n.isin(sentinels))


# ---------- labels ----------
def _norm(x):
    """lowercase, '&' -> 'and', punctuation/spacing collapsed, so
    'Home & Kitchen', 'home and kitchen' and 'HOME&KITCHEN ' all match."""
    t = str(x).lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def canon_labels(s, canonical, aliases=None, cutoff=0.7, unknown="Unknown"):
    """Maps spelling variants to canonical values.
    Order: exact (normalised) -> alias dict -> prefix -> fuzzy. Else `unknown`.
    Returns (cleaned series, sorted list of labels that could not be matched)."""
    base = {_norm(c): c for c in canonical}
    for k, v in (aliases or {}).items():
        base[_norm(k)] = v
    cache, unmatched = {}, set()

    def f(v):
        if pd.isna(v) or _norm(v) == "":
            return unknown
        k = _norm(v)
        if k in cache:
            return cache[k]
        if k in base:
            r = base[k]
        else:
            pre = [c for nk, c in base.items() if nk.startswith(k) or k.startswith(nk)]
            if len(set(pre)) == 1:
                r = pre[0]
            else:
                m = difflib.get_close_matches(k, list(base), n=1, cutoff=cutoff)
                r = base[m[0]] if m else None
        if r is None:
            unmatched.add(str(v))
            r = unknown
        cache[k] = r
        return r
    return s.map(f), sorted(unmatched)


# ---------- duplicates ----------
def dedup_exact(df, dq, table):
    n0 = len(df)
    out = df.drop_duplicates()
    dq.log("exact_duplicates", table, "*", n0, len(out), "drop_duplicates")
    return out


def customer_merge_map(df, id_col, email_col, phone_col, max_group=5):
    """Same normalised email OR same phone (last 10 digits) => same person.
    Union-find. Keys shared by more than `max_group` ids are treated as
    placeholders (e.g. 0000000000) and ignored. Never matches on name.
    Returns DataFrame[dup_id, master_id]; master = smallest id in the group."""
    ids = df[id_col].astype(str).tolist()
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    keys = {"e": df[email_col].astype("string").str.strip().str.lower(),
            "p": df[phone_col].astype("string").str.replace(r"\D", "", regex=True).str[-10:]}
    for tag, col in keys.items():
        col = col.where(col.str.len() > 5)
        tmp = pd.DataFrame({"id": df[id_col].astype(str), "k": col}).dropna()
        for _, g in tmp.groupby("k"):
            if 1 < g["id"].nunique() <= max_group:
                first = g["id"].iloc[0]
                for other in g["id"].iloc[1:]:
                    union(first, other)
    m = pd.DataFrame({"dup_id": ids, "master_id": [find(i) for i in ids]})
    return m[m.dup_id != m.master_id].reset_index(drop=True)


# ---------- prices ----------
def repair_unit_price(items, price_col, list_col, dq, table, lo=0.3, hi=3.0):
    """unit_price that is NaN, <=0 or far from list_price (ratio outside lo..hi)
    is replaced by list_price. If list_price is also unusable the row goes to
    rejects with BAD_PRICE. Returns (kept rows, rejected rows)."""
    p, lp = items[price_col], items[list_col]
    bad = p.isna() | (p <= 0) | ((p / lp) > hi) | ((p / lp) < lo)
    fixable = bad & lp.notna() & (lp > 0)
    items = items.copy()
    items.loc[fixable, price_col] = lp[fixable]
    dq.log("bad_unit_price", table, price_col, int(bad.sum()), int((bad & ~fixable).sum()),
           f"replaced by {list_col} when valid; else rejected BAD_PRICE")
    rej = items[bad & ~fixable]
    dq.reject(rej, table, "BAD_PRICE")
    return items[~(bad & ~fixable)], rej


def fill_discount(items, qty_col, price_col, disc_col, pct_col):
    """Missing discount_amount = quantity * unit_price * pct/100."""
    gross = items[qty_col] * items[price_col]
    calc = gross * items[pct_col].fillna(0) / 100
    return items[disc_col].fillna(calc)
