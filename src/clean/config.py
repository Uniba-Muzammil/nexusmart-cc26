"""Cleaning configuration. Canonical label sets, aliases and thresholds live here
(not in the code) so the hour-6 data drop only needs a config tweak, and any
label we have never seen falls back to fuzzy match, then 'Unknown' + a DQ log line."""

VALID_FROM, VALID_TO = "2024-01-01", "2025-06-30"      # problem statement s4 rules
QTY_MAX = 100            # a single line above this is treated as corrupt (observed outliers: 500)
PRICE_RATIO = (0.3, 3.0) # unit_price/list_price outside this => corrupt (normal range 1.00-1.045)
LAST_ONTIME_DAYS = 7     # on-time delivery threshold (days shipped -> delivered)
SHIP_DAYS_MAX = 60       # longer delivery windows are treated as bad dates
BIRTH_YEAR = (1930, 2010)
RATING = (1, 5)

CANON = {
    "order_status": ["Delivered", "Cancelled", "Returned", "In Transit"],
    "channel": ["App", "Web", "Mobile Web"],
    "payment_method": ["COD", "Card", "JazzCash", "EasyPaisa", "Bank Transfer"],
    "payment_status": ["Paid", "Cancelled", "Refunded", "Pending"],
    "delivery_status": ["Delivered", "In Transit", "Returned to Seller"],
    "courier": ["TCS", "Leopards", "M&P", "Trax", "PostEx", "BlueEx"],
    "return_status": ["Refunded", "Approved", "Rejected"],
    "return_reason": ["Size/fit issue", "Not as described", "Quality issue", "Damaged product",
                      "Changed mind", "Wrong item delivered", "Colour mismatch",
                      "Late delivery", "Missing parts"],
    "category": ["Fashion", "Mobile & Accessories", "Home & Kitchen", "Electronics",
                 "Beauty & Personal Care", "Footwear", "Grocery", "Sports & Outdoors",
                 "Health & Wellness", "Toys & Games", "Books & Stationery", "Automotive"],
    "gender": ["M", "F"],
    "seller_tier": ["Gold", "Silver", "Bronze"],
    "province": ["Punjab", "Sindh", "Khyber Pakhtunkhwa", "Balochistan", "Gilgit-Baltistan",
                 "Azad Kashmir", "Islamabad"],
}

ALIASES = {
    "order_status": {"complete": "Delivered", "completed": "Delivered", "canceled": "Cancelled",
                     "shipped": "In Transit", "return": "Returned"},
    "channel": {"website": "Web", "mobile app": "App", "mweb": "Mobile Web"},
    "payment_method": {"cash on delivery": "COD", "credit/debit card": "Card", "debit card": "Card",
                       "jazz cash": "JazzCash", "easy paisa": "EasyPaisa", "bank trf": "Bank Transfer"},
    "payment_status": {"complete": "Paid", "success": "Paid", "refund": "Refunded", "canceled": "Cancelled"},
    "delivery_status": {"completed": "Delivered", "complete": "Delivered", "shipped": "In Transit",
                        "rto": "Returned to Seller", "return to seller": "Returned to Seller"},
    "courier": {"tcs express": "TCS", "t.c.s": "TCS", "leopard courier": "Leopards",
                "mnp": "M&P", "blue ex": "BlueEx", "blue-ex": "BlueEx"},
    "return_status": {"refund": "Refunded", "declined": "Rejected"},
    "return_reason": {
        "different from picture": "Not as described", "damaged": "Damaged product",
        "item damaged": "Damaged product", "poor quality": "Quality issue", "bad quality": "Quality issue",
        "quality": "Quality issue", "size issue": "Size/fit issue", "doesn't fit": "Size/fit issue",
        "size/fit": "Size/fit issue", "wrong size": "Size/fit issue", "change of mind": "Changed mind",
        "no longer needed": "Changed mind", "changed my mind": "Changed mind",
        "received wrong product": "Wrong item delivered", "wrong item": "Wrong item delivered",
        "color mismatch": "Colour mismatch", "colour different": "Colour mismatch",
        "wrong colour": "Colour mismatch", "delivered late": "Late delivery", "too late": "Late delivery",
        "late": "Late delivery", "parts missing": "Missing parts", "missing part": "Missing parts",
        "incomplete": "Missing parts"},
    "category": {"mobile acc": "Mobile & Accessories", "mobiles": "Mobile & Accessories",
                 "clothing": "Fashion", "fashion and apparel": "Fashion", "shoes": "Footwear",
                 "electronic items": "Electronics", "elec": "Electronics", "auto": "Automotive",
                 "car accessories": "Automotive", "sports": "Sports & Outdoors", "beauty": "Beauty & Personal Care",
                 "personal care": "Beauty & Personal Care", "books": "Books & Stationery",
                 "stationary": "Books & Stationery", "health": "Health & Wellness", "toys": "Toys & Games",
                 "groceries": "Grocery", "food and grocery": "Grocery"},
    "gender": {"male": "M", "female": "F"},
    "seller_tier": {},
    "province": {"panjab": "Punjab", "kp": "Khyber Pakhtunkhwa", "kpk": "Khyber Pakhtunkhwa",
                 "sind": "Sindh", "gb": "Gilgit-Baltistan", "gilgit baltistan": "Gilgit-Baltistan",
                 "baluchistan": "Balochistan", "azad jammu and kashmir": "Azad Kashmir"},
}
