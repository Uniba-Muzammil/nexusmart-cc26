# Cleaning module (`src/clean/`)

```
python src/clean/clean_all.py data out          # clean -> out/*.csv + dq_log.csv + reject.csv
python src/clean/sensitivity.py data out        # B3: impact of each big decision -> out/sensitivity.csv
python src/clean/make_dq_report.py out docs/data_quality_report.pdf data   # needs: pip install reportlab (3rd arg = raw CSV folder)
```
Needs only `pandas` and `numpy` (works on pandas 2.2 and 3.x; output byte-identical). Re-running overwrites `out/` with identical files (idempotent).

| File | Purpose |
|---|---|
| `nx_config.py` | thresholds + label alias dictionaries. **Hour-6: new spelling -> add here only.** |
| `toolkit.py` | parsing (dates/numbers/quantities), `LabelMapper` (exact -> fuzzy -> `Unknown`), `Audit` (dq_log + reject) |
| `clean_schema.py` | column types of every clean table; `check out` verifies the CSVs, `sql` prints the DDL (`sql/clean_schema.sql`) |
| `clean_all.py` | one function per table; `run(data_dir, out_dir)` returns `{table: {rows_read, rows_rejected, rows_loaded}}`; `validate_raw(data_dir)` returns a list of problems (use in the DAG `validate_raw` task) |

Load into Postgres: `python tools/load_postgres.py out "<dsn>"` (schemas `clean` and `audit`). Full guide for A and C: `docs/HANDOFF_MEMBER_B.md`.

## Output tables (names = `clean` schema)
`customers, customer_map, products, product_map, sellers, locations, orders, order_items, payments, shipping, returns` + `dq_log`, `reject` (`audit` schema).
Extra columns the warehouse can use: `orders.discount_pct, orphan_customer, date_repair, order_total_calc`; `order_items.gross_amount, net_amount, unit_cost, cost_source, orphan_product, qty_fix, price_fix`; `payments.n_payments, is_primary`;
`returns.is_valid_return`; `shipping.shipping_days, fee_imputed`; `products.cost_imputed`.
`customers`/`products` hold master rows only; `orders.customer_id` and `order_items.product_id` are already mapped to the master id (original id kept in `*_orig`).

## Rules in one table
| Problem | Rule |
|---|---|
| Exact duplicates (orders 3,200, payments 3,296) | `drop_duplicates`, counts logged |
| Dates | 3+ formats parsed strictly, slash = dd/mm/yyyy. Impossible / out-of-window order date repaired as `shipped_date - 1 day` (shipped-order is 0-2 days on all valid rows), else `payment_date`, else rejected `BAD_DATE` / `DATE_OUT_OF_RANGE` (13 orders) |
| Labels | alias dictionary -> fuzzy (difflib >= 0.86) -> `Unknown` + `UNMATCHED LABELS` row in dq_log |
| `Rs. 2,290`, 9999999, negatives | parsed / treated as missing |
| Quantity | words -> numbers, negative -> abs, 500 and >10 recovered from `order_total` (632); unrecoverable -> `BAD_QTY` (9) |
| Unit price | ratio to list price outside 0.5-2.0 (legit data sits in 0.99-1.10) or <=0 / sentinel -> solved from `order_total` (1,528), else list price (29) |
| Discount | recomputed `round(qty x price x code%)` (matches 99.6% of raw rows; fills 31.5k blanks, fixes 883 inflated) |
| Duplicate customers | union-find on identical email OR phone (phone also needs name similarity >= 0.7); never name alone; 45,000 -> 42,444, `customer_map` |
| Duplicate products | normalised name + brand + category; 3,200 -> 3,174, `product_map` |
| Cost (COGS) | `cost_price` missing / <= 0 / above list price -> `list_price x median(cost/list)` of the category (flag `cost_imputed`). Lines of orphan products -> `unit_cost = unit_price x median(cost/price)` (flag `cost_source = NO_PRODUCT_COST_ESTIMATE`). FactSales `CostAmount = unit_cost x quantity` |
| Split payments | 2 payment rows on an order = the order was paid in two parts (they add up to `order_total`). `is_primary = 1` marks one row per order (Paid/Refunded first, then larger part) - FactSales uses it |
| Orphans | customer (321 orders) / product (932 lines) kept, flagged, mapped to Unknown later; orphan returns (139) rejected `ORPHAN_RETURN` |
| Shipping | delivered < shipped (exactly -2d, 1,269) and > 60 days (266) -> delivered_date NULL; fee sentinel/blank -> mean valid fee, flagged |
| Returns | `Rejected` = not valid; valid returns with refund <= 0 or > line gross -> line gross; bad return date -> order_date + median lag |

## Settings that can change without editing code (environment variables)
| Variable | Default | Use |
|---|---|---|
| `NX_DATE_MIN`, `NX_DATE_MAX` | 2024-01-01, 2025-06-30 | valid order-date window (if the Hour-6 data covers other months) |
| `NX_GATE_SCALE` | 1 | multiplies every reject-% limit of the quality gate (set 3 only after reading dq_log / reject) |

## Key assumptions (paste into the README; figures are for the supplied dataset, the DQ report section 8 regenerates them)
Four decisions are written up because they move a headline number, or a judge will ask:

1. **Impossible order dates are repaired, not rejected.** 1,592 orders are rebuilt as `shipped_date - 1 day` (1,455) or `payment_date - 1 day` (137); 13 with neither date are rejected. Shipped-minus-order is 0-2 days on 100% of valid orders, so the repair is at most about 1 day off. Rejecting instead would remove **1.03% of NMV** (beyond the 1% tolerance) and leave holes in the monthly trend.
2. **Duplicate customers are merged on email or phone, never on name alone.** 45,000 records become 42,444 (`customer_map` keeps every link). Active Customers is 31,779 merged vs 32,836 unmerged (**-3.2%**). Revenue is unaffected; repeat rate, CLV and RFM are.
3. **Order lines of unknown products are kept and their cost is estimated.** 932 lines (0.36% of NMV) reference product ids that do not exist; they are mapped to the Unknown product. `unit_cost = unit_price x 0.572`. Costing them at zero would overstate margin by 0.22 pt, excluding them changes it by -0.04 pt (tolerance 0.5 pt).
4. **`cost_price` above `list_price` is treated as corrupt.** All 65 such products with an untouched list price have cost = exactly 1.50 x list price, while normal products never exceed 0.97, so it is a systematic fault. They are imputed with the category median cost/list ratio (0.61). Keeping the raw costs would lower margin by **2.0 pt** (beyond tolerance). Imputation error on products with a genuine cost: median 5%, p90 14%; a 5% bias moves margin 0.26 pt.

### If a judge asks
- *Why repair dates instead of rejecting?* Repair uses real data from the same order (its own shipment date); rejecting loses 1.03% of NMV and distorts months. Only 13 orders had nothing to repair from and they are in the reject table with a reason code.
- *How do you know two customers are the same person?* Same normalised email, or same phone plus similar name (>= 0.7). Name alone is never used. The mapping table lets you undo any merge.
- *What happens to a sale of a product you do not know?* It stays in revenue (the sale happened), the product is shown as Unknown, cost is estimated from the typical cost-to-price ratio and flagged so it can be filtered out.
- *Why not trust cost_price as given?* 65 products have cost exactly 1.5x list price, which never happens in normal data; trusting it would drop margin by 2 pt.
- *What is a split payment?* 4,815 orders were paid in two parts (about 60/40). They are not duplicates; amounts add up to the order total. FactSales uses the main (larger) part's method.

## Hour-6 drill (B)
1. `python src/clean/clean_all.py data out`  (or let the DAG run it)
2. Open `out/dq_log.csv`, filter `issue` = `UNMATCHED LABELS` / `UNRECOGNISED DATE FORMAT` -> add spellings to `nx_config.LABELS` (or a pattern to `toolkit._PATTERNS`) -> rerun.
3. Check `TABLE SUMMARY` rows and `reject.csv` for anything new; the run **fails** if a table rejects more than `nx_config.MAX_REJECT_PCT`.
4. `sensitivity.py` + `make_dq_report.py` regenerate the report with the new numbers (including the key-assumption figures).
5. Rehearse first: `python tools/stress_test.py data` builds a mutated copy in `stress/data` (new labels, new date formats, `N/A`, extra columns, duplicate keys, orphans); run `clean_all.py stress/data stress/out` and make sure it finishes and logs the surprises.
