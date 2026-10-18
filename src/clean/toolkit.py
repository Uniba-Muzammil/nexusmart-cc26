"""Small reusable helpers: parsing, label mapping, audit logging."""
import difflib
import json
import re

import numpy as np
import pandas as pd

import nx_config as C

# ------------------------------------------------------------------ audit (dq_log + reject)
DQ_COLS = ["step", "table", "issue", "column", "before_count", "after_count", "action", "assumption"]
REJ_COLS = ["table", "record_key", "reason_code", "detail", "raw_row"]


class Audit:
    """Collects every cleaning decision (dq_log) and every unrepairable record (reject)."""

    def __init__(self):
        self.dq, self.rej, self.step = [], [], 0
        self.unmatched = {}          # (table, column) -> {value: count}

    def log(self, table, issue, column="", before=None, after=None, action="", assumption=""):
        self.step += 1
        self.dq.append([self.step, table, issue, column, before, after, action, assumption])

    def reject(self, df, table, key, reason, detail=""):
        """Move rows into the reject table with a reason code. Never a silent delete."""
        if df is None or len(df) == 0:
            return 0
        raw = df.apply(lambda r: json.dumps({k: (None if pd.isna(v) else str(v)) for k, v in r.items()}), axis=1)
        out = pd.DataFrame({"table": table, "record_key": df[key].astype(str).values,
                            "reason_code": reason, "detail": detail, "raw_row": raw.values})
        self.rej.append(out)
        return len(out)

    def note_unmatched(self, table, column, values):
        d = self.unmatched.setdefault((table, column), {})
        for v, n in values.items():
            d[v] = d.get(v, 0) + int(n)

    def dq_frame(self):
        rows = list(self.dq)
        for (t, c), d in self.unmatched.items():
            rows.append([0, t, "UNMATCHED LABELS", c, sum(d.values()), sum(d.values()),
                         f"mapped to '{C.UNKNOWN}'", "add to nx_config.LABELS: " + "; ".join(f"{k!r} x{v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:25])])
        return pd.DataFrame(rows, columns=DQ_COLS)

    def reject_frame(self):
        return pd.concat(self.rej, ignore_index=True) if self.rej else pd.DataFrame(columns=REJ_COLS)

    def rejected_count(self, table):
        return int(sum((r["table"] == table).sum() for r in self.rej))


# ------------------------------------------------------------------ text
def strip_all(df):
    """Trim whitespace in every text column; blank -> NaN."""
    df = df.copy()
    for c in df.columns:
        s = df[c].astype("string").str.strip()
        df[c] = s.mask((s == "") | s.str.lower().isin(C.NULL_STRINGS), pd.NA)
    return df


def norm_label(s):
    s = str(s).lower().replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[-_/]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


class LabelMapper:
    """canonical label lookup: exact alias -> fuzzy alias -> UNKNOWN (and recorded)."""

    def __init__(self, name):
        self.name = name
        self.lookup = {}
        for canon, aliases in C.LABELS[name].items():
            self.lookup[norm_label(canon)] = canon
            for a in aliases:
                self.lookup[norm_label(a)] = canon

    def map(self, series, audit, table, column=None):
        column = column or series.name
        s = series.astype("string")
        nl = s.map(lambda v: norm_label(v) if pd.notna(v) else None)
        out = nl.map(self.lookup)
        miss = out.isna() & nl.notna() & (nl != "")
        fuzzy_n, unmatched = 0, {}
        if miss.any():
            keys = list(self.lookup)
            cache = {}
            for v in nl[miss].unique():
                m = difflib.get_close_matches(v, keys, n=1, cutoff=C.FUZZY_CUTOFF)
                cache[v] = self.lookup[m[0]] if m else None
            fz = nl[miss].map(cache)
            out[miss] = fz
            fuzzy_n = int(fz.notna().sum())
            for raw in s[miss][fz.isna()]:
                unmatched[raw] = unmatched.get(raw, 0) + 1
        blank = int(s.isna().sum())
        if unmatched:
            audit.note_unmatched(table, column, unmatched)
        before = int(s.str.strip().nunique())
        out = out.fillna(C.UNKNOWN)
        audit.log(table, "INCONSISTENT LABELS", column, before, int(out.nunique()),
                  f"mapped to canonical set via nx_config.LABELS['{self.name}']",
                  f"{fuzzy_n} rows matched fuzzily; {sum(unmatched.values())} unmatched -> '{C.UNKNOWN}'; {blank} blank -> '{C.UNKNOWN}'")
        return out.astype("object")


# ------------------------------------------------------------------ numbers
def to_num(series):
    """'Rs. 2,290' / 'PKR 1,000' / '1.0' -> float. Unparseable -> NaN."""
    s = series.astype("string").str.lower()
    s = s.str.replace(r"(rs\.?|pkr|₨)", "", regex=True).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="coerce").astype("float64")


def to_qty(series):
    """quantity: digits, '2.0', words ('two'). Returns signed float (sign handled by caller)."""
    s = series.astype("string").str.lower().str.strip()
    s = s.replace({k: str(v) for k, v in C.QTY_WORDS.items()})
    return pd.to_numeric(s, errors="coerce").astype("float64")


def is_sentinel(x):
    return x.isin(list(C.SENTINELS)) | (x.abs() >= C.ABS_PRICE_MAX)


# ------------------------------------------------------------------ dates
_PATTERNS = [
    (r"^\d{4}-\d{1,2}-\d{1,2}$", "%Y-%m-%d"),
    (r"^\d{1,2}/\d{1,2}/\d{4}$", "%d/%m/%Y"),         # slash dates are day/month/year (spec rule)
    (r"^[A-Za-z]{3,9} \d{1,2},? \d{4}$", None),       # 'Nov 23 2024', 'November 23, 2024'
    (r"^\d{1,2}-\d{1,2}-\d{4}$", "%d-%m-%Y"),
    (r"^\d{4}/\d{1,2}/\d{1,2}$", "%Y/%m/%d"),
    (r"^\d{1,2} [A-Za-z]{3,9} \d{4}$", None),
    (r"^\d{1,2}-[A-Za-z]{3,9}-\d{4}$", None),
    (r"^\d{4}\.\d{1,2}\.\d{1,2}$", "%Y.%m.%d"),
    (r"^\d{1,2}\.\d{1,2}\.\d{4}$", "%d.%m.%Y"),
    (r"^\d{8}$", "%Y%m%d"),
]


def _prep_dates(series):
    """trim, drop a trailing time part ('2024-05-12 14:33:00', '2024-05-12T14:33:00Z')."""
    s = series.astype("string").str.strip()
    return s.str.replace(r"[T\s]+\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$", "", regex=True)


def parse_date(series):
    """Parse the known date formats strictly. Impossible dates (30 Feb, month 13, 00/00) -> NaT."""
    s = _prep_dates(series)
    s = s.mask(s.str.lower().isin(C.NULL_STRINGS), pd.NA)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for pat, fmt in _PATTERNS:
        m = s.str.match(pat).fillna(False)
        if not m.any():
            continue
        sub = s[m].str.replace(",", "", regex=False)
        if fmt:
            parsed = pd.to_datetime(sub, format=fmt, errors="coerce")
        else:
            parsed = pd.to_datetime(sub, format="%b %d %Y", errors="coerce")
            parsed = parsed.fillna(pd.to_datetime(sub, format="%B %d %Y", errors="coerce"))
            parsed = parsed.fillna(pd.to_datetime(sub.str.replace("-", " ", regex=False), format="%d %b %Y", errors="coerce"))
            parsed = parsed.fillna(pd.to_datetime(sub, format="%d %b %Y", errors="coerce"))
            parsed = parsed.fillna(pd.to_datetime(sub, format="%d %B %Y", errors="coerce"))
        out[m] = parsed
    return out


def unrecognised_dates(series):
    """Non-blank values that match NO known date pattern (a brand-new format, as opposed to an
    impossible date like 30 Feb which matches a pattern but cannot be parsed)."""
    s = _prep_dates(series)
    s = s.mask(s.str.lower().isin(C.NULL_STRINGS), pd.NA)
    known = pd.Series(False, index=s.index)
    for pat, _ in _PATTERNS:
        known |= s.str.match(pat).fillna(False)
    return s[s.notna() & ~known]


def in_range(d):
    return d.between(C.DATE_MIN, C.DATE_MAX)


def pct_from_code(series):
    """discount_code -> fraction. 'SAVE15' / '15' -> 0.15. Blank -> 0."""
    d = series.astype("string").str.extract(r"(\d+)")[0]
    return (pd.to_numeric(d, errors="coerce") / 100).fillna(0.0)


def half_up(x):
    return np.floor(x + 0.5)
