"""NexusMart cleaning configuration.

Everything that is a *judgement call* lives here (thresholds, label aliases) so that the
Hour-6 data drop can be handled by editing this file only. Labels are matched after
normalisation (lowercase, '&' -> 'and', punctuation stripped, spaces collapsed), so you
only need to add the normalised form of a new spelling to the right alias list.
"""
import os

import pandas as pd

# ---------------------------------------------------------------- business rules (spec)
# Hour-6 safety: window can be widened without touching code (env NX_DATE_MIN / NX_DATE_MAX, ISO dates)
DATE_MIN = pd.Timestamp(os.environ.get("NX_DATE_MIN", "2024-01-01"))
DATE_MAX = pd.Timestamp(os.environ.get("NX_DATE_MAX", "2025-06-30"))

# strings that mean "missing" in exports (matched case-insensitively after trimming)
NULL_STRINGS = {"null", "none", "nan", "n/a", "na", "#n/a", "-", "--", "?", "nil"}

# ---------------------------------------------------------------- thresholds
QTY_MAX = 10                 # legit quantities observed: 1..6. Anything above is an outlier (500 seen)
PRICE_RATIO_MIN = 0.5        # unit_price / list_price. Legit data lies in 0.99-1.10 with a clean gap
PRICE_RATIO_MAX = 2.0        #   up to 0.3 and from 3.0, so 0.5..2.0 safely separates good from corrupt
ABS_PRICE_MAX = 1_000_000    # anything >= this is a sentinel (9999999)
SENTINELS = {9999999, 99999999, 999999, -1}
SHIPPING_DAYS_MAX = 60       # delivered - shipped above this is corrupt (legit tail stops ~30 days)
FEE_MAX = 50_000             # shipping fee above this is a sentinel
BIRTH_YEAR_MIN, BIRTH_YEAR_MAX = 1940, 2010
RATING_MIN, RATING_MAX = 1.0, 5.0
FUZZY_CUTOFF = 0.86          # difflib similarity for unseen label spellings (Hour-6 safety net)
PHONE_NAME_SIM = 0.70        # a phone-only duplicate customer match must also have similar names
GATE_SCALE = float(os.environ.get("NX_GATE_SCALE", "1"))   # e.g. NX_GATE_SCALE=3 relaxes every limit x3 (never silently off)
MAX_REJECT_PCT = {           # quality gate used by the DAG (fail pipeline if exceeded)
    "orders": 1.0, "order_items": 1.0, "payments": 1.0, "shipping": 1.0, "returns": 2.0,
}

# ---------------------------------------------------------------- label dictionaries
# canonical -> list of normalised aliases. Canonical itself is always accepted.
LABELS = {
    "order_status": {
        "Delivered": ["delivered", "deliverd", "complete", "completed"],
        "Cancelled": ["cancelled", "canceled"],
        "Returned": ["returned", "return"],
        "In Transit": ["in transit", "intransit", "shipped"],
    },
    "channel": {
        "App": ["app", "mobile app"],
        "Web": ["web", "website"],
        "Mobile Web": ["mobile web", "mweb"],
    },
    "payment_method": {
        "COD": ["cod", "cash on delivery"],
        "Card": ["card", "credit debit card", "debit card", "credit card"],
        "JazzCash": ["jazzcash", "jazz cash"],
        "EasyPaisa": ["easypaisa", "easy paisa"],
        "Bank Transfer": ["bank transfer", "bank trf"],
    },
    "payment_status": {
        "Paid": ["paid", "complete", "completed", "success", "successful"],
        "Cancelled": ["cancelled", "canceled"],
        "Refunded": ["refunded", "refund"],
        "Pending": ["pending"],
    },
    "courier": {
        "TCS": ["tcs", "tcs express", "tcs"],
        "Leopards": ["leopards", "leopard courier", "leopard"],
        "M&P": ["mandp", "m and p", "mnp", "m p"],
        "Trax": ["trax"],
        "PostEx": ["postex", "post ex"],
        "BlueEx": ["blueex", "blue ex"],
    },
    "delivery_status": {
        "Delivered": ["delivered", "deliverd", "complete", "completed"],
        "In Transit": ["in transit", "intransit", "shipped"],
        "Returned to Seller": ["returned to seller", "return to seller", "rto"],
    },
    "return_status": {
        "Refunded": ["refunded", "refund"],
        "Approved": ["approved"],
        "Rejected": ["rejected", "declined"],
    },
    "return_reason": {
        "Size/Fit": ["size fit issue", "size fit", "size issue", "doesnt fit", "wrong size"],
        "Not as described": ["not as described", "different from picture"],
        "Quality issue": ["quality issue", "poor quality", "bad quality", "quality"],
        "Damaged": ["damaged product", "damaged", "item damaged"],
        "Changed mind": ["changed mind", "change of mind", "changed my mind", "no longer needed"],
        "Wrong item": ["wrong item delivered", "wrong item", "received wrong product"],
        "Colour mismatch": ["colour mismatch", "color mismatch", "colour different", "wrong colour", "wrong color"],
        "Late delivery": ["late delivery", "delivered late", "too late", "late"],
        "Missing parts": ["missing parts", "parts missing", "missing part", "incomplete"],
    },
    "category": {
        "Fashion": ["fashion", "clothing", "fashion and apparel", "apparel"],
        "Mobile & Accessories": ["mobile and accessories", "mobile acc", "mobiles", "mobile accessories"],
        "Home & Kitchen": ["home and kitchen", "homeandkitchen", "home kitchen"],
        "Electronics": ["electronics", "electronic items", "elec", "electronic"],
        "Beauty & Personal Care": ["beauty and personal care", "beauty", "personal care"],
        "Footwear": ["footwear", "shoes"],
        "Grocery": ["grocery", "groceries", "food and grocery"],
        "Sports & Outdoors": ["sports and outdoors", "sports", "outdoors"],
        "Health & Wellness": ["health and wellness", "health", "wellness"],
        "Toys & Games": ["toys and games", "toys", "games"],
        "Books & Stationery": ["books and stationery", "books", "stationary", "stationery"],
        "Automotive": ["automotive", "auto", "car accessories"],
    },
    "gender": {
        "M": ["m", "male", "man"],
        "F": ["f", "female", "woman"],
    },
    "seller_tier": {
        "Gold": ["gold"], "Silver": ["silver"], "Bronze": ["bronze"],
    },
    "province": {
        "Punjab": ["punjab", "panjab"],
        "Sindh": ["sindh", "sind"],
        "Khyber Pakhtunkhwa": ["khyber pakhtunkhwa", "kp", "kpk", "khyber pakhtunkhua", "nwfp"],
        "Balochistan": ["balochistan", "baluchistan"],
        "Gilgit-Baltistan": ["gilgit baltistan", "gb", "gilgitbaltistan"],
        "Azad Kashmir": ["azad kashmir", "azad jammu and kashmir", "ajk", "azad jammu kashmir"],
        "Islamabad": ["islamabad", "ict", "islamabad capital territory"],
    },
    "population_tier": {
        "Metro": ["metro"], "Tier-2": ["tier 2", "tier2"], "Tier-3": ["tier 3", "tier3"],
    },
}
# value used when a label is blank / cannot be matched (flagged in dq_log as UNMATCHED LABELS)
UNKNOWN = "Unknown"

# quantity written as words
QTY_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10}

# reject reason codes (documented in README / DQ report)
REASONS = {
    "BAD_DATE": "order date impossible/unparseable and not repairable from shipping/payment dates",
    "DATE_OUT_OF_RANGE": "order date outside 2024-01-01..2025-06-30 and not repairable",
    "BAD_PRICE": "unit price invalid and no list price / order total to repair it from",
    "BAD_QTY": "quantity invalid and not recoverable from order_total",
    "ORPHAN_RETURN": "return references an order_item that does not exist",
    "PARENT_ORDER_REJECTED": "child record of an order that was rejected",
    "DUPLICATE_KEY": "primary key repeated with different content (first kept)",
    "ORPHAN_ORDER": "child record whose order_id is not in orders",
}

# columns the pipeline needs in every raw file (validate_raw task uses this; extra columns are ignored)
REQUIRED_COLUMNS = {
    "customers": ["customer_id", "full_name", "email", "phone", "gender", "registration_date", "city_id", "birth_year"],
    "products": ["product_id", "product_name", "category", "sub_category", "brand", "list_price", "cost_price", "weight_kg", "seller_id"],
    "sellers": ["seller_id", "seller_name", "join_date", "seller_tier", "city_id", "rating"],
    "locations": ["city_id", "city", "province", "region", "latitude", "longitude", "population_tier"],
    "orders": ["order_id", "customer_id", "order_date", "order_status", "ship_city_id", "order_total", "discount_code", "channel"],
    "order_items": ["order_item_id", "order_id", "product_id", "seller_id", "quantity", "unit_price", "discount_amount"],
    "payments": ["payment_id", "order_id", "payment_method", "payment_status", "amount", "payment_date"],
    "shipping": ["shipment_id", "order_id", "courier", "shipped_date", "delivered_date", "shipping_fee", "delivery_status"],
    "returns": ["return_id", "order_item_id", "return_date", "return_reason", "return_status", "refund_amount"],
}
