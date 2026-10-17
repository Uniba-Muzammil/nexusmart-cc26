# memberB_cleaning v3 (v2 + type contract + loader + rename) (drop-in for src/clean/, docs/data_quality_report.pdf, out_samples/)

Real-data output is byte-identical to your original for customers, customer_map, products, product_map, sellers,
locations, orders, shipping, returns and reject. Changed: payments (2 new columns + 55 split-payment amounts),
order_items (2 new columns). Re-running gives identical files (idempotent).

## Round 1 (already sent)
crash fix in clean_order_items; split payments (`n_payments`, `is_primary`); "NULL"/"N/A" strings = missing;
more date formats; env overrides NX_DATE_MIN / NX_DATE_MAX / NX_GATE_SCALE; tools/stress_test.py.

## Round 2 (this zip)
1. Margin in the sensitivity table (sensitivity.py): imputed cost excluded / +-5% / +-20% stress, cost>list kept raw,
   orphan COGS = 0 / excluded. Result: cost>list kept raw = -2.0 pt (YES), everything else inside 0.5 pt.
   Evidence for treating cost>list as corrupt: all 65 products have cost = exactly 1.50 x list; normal max is 0.97.
2. Orphan-product cost (clean_all.py): `order_items.unit_cost` and `cost_source` (PRODUCT / PRODUCT_IMPUTED /
   NO_PRODUCT_COST_ESTIMATE). Orphan lines: unit_cost = unit_price x 0.572 (median cost/price). C: CostAmount = unit_cost x quantity.
3. DQ report (make_dq_report.py, now takes the raw data folder as 3rd argument):
   - Section 1 is a per-table waterfall (read - duplicates - merged - rejected = loaded) with a "Reconciles?" check and reject reasons
   - Section 3 shows raw distinct spellings vs trimmed (74 -> 62 -> 12) with an explanation
   - Section 6 validates split payments and is_primary; Section 7 limitations updated
   - NEW Section 8: key assumptions with this run's numbers (dates, customer merge, orphan cost, cost>list)
4. README_CLEANING.md: key-assumptions block to paste into the main README, judge Q&A, env variables, new columns.
5. 8-page PDF regenerated: docs/data_quality_report.pdf. out_samples/ has dq_log, reject, sensitivity.
Run order: clean_all.py data out -> sensitivity.py data out -> make_dq_report.py out docs/data_quality_report.pdf data

## Round 3 (v3)
1. `src/clean/clean_schema.py` + `sql/clean_schema.sql`: type contract for all 11 clean tables (ids TEXT, dates DATE, money NUMERIC, flags SMALLINT).
   `python src/clean/clean_schema.py check out` verifies out/*.csv (columns, PK, types, soft FKs).
2. `tools/load_postgres.py`: TRUNCATE + COPY into schemas `clean` and `audit`, one transaction, idempotent. Tested on a real Postgres.
3. `sql/example_fact_sales.sql`: verified line-grain FactSales view (is_primary payment, unit_cost*quantity, valid returns pre-aggregated, shipping fee split).
4. `config.py` renamed `nx_config.py` (Airflow has a config/ folder). Pipeline output unchanged; only dq_log text says nx_config.LABELS.
5. `docs/HANDOFF_MEMBER_B.md`: GitHub steps, A/C instructions, Hour-6 runbook, tested vs not tested.
6. `requirements-clean.txt`, `.gitignore`.
NOTE: docs/data_quality_report.pdf is from the previous run; rerun make_dq_report.py on the real data to refresh the text.
