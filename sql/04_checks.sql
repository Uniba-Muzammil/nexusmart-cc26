-- 04_checks.sql : ek hi result set, har row = ek check (check_name, failed_rows, status). failed_rows > 0 matlab FAIL.
-- A ka quality_checks task: koi row failed_rows > 0 ho to task fail.
WITH c AS (
  SELECT 'fact rows = clean.order_items rows'::text AS check_name,
         ABS((SELECT COUNT(*) FROM clean.order_items) - (SELECT COUNT(*) FROM mart.fact_sales))::numeric AS failed_rows
  UNION ALL SELECT 'duplicate order_item_id',
         ((SELECT COUNT(*) FROM mart.fact_sales) - (SELECT COUNT(DISTINCT order_item_id) FROM mart.fact_sales))::numeric
  UNION ALL SELECT 'NULL keys in fact',
         (SELECT COUNT(*) FROM mart.fact_sales WHERE date_key IS NULL OR customer_key IS NULL OR product_key IS NULL OR seller_key IS NULL OR location_key IS NULL)::numeric
  UNION ALL SELECT 'fact keys missing in dimensions',
         ((SELECT COUNT(*) FROM mart.fact_sales f LEFT JOIN mart.dim_date x ON x.date_key = f.date_key WHERE x.date_key IS NULL)
        + (SELECT COUNT(*) FROM mart.fact_sales f LEFT JOIN mart.dim_customer x ON x.customer_key = f.customer_key WHERE x.customer_key IS NULL)
        + (SELECT COUNT(*) FROM mart.fact_sales f LEFT JOIN mart.dim_product x ON x.product_key = f.product_key WHERE x.product_key IS NULL)
        + (SELECT COUNT(*) FROM mart.fact_sales f LEFT JOIN mart.dim_seller x ON x.seller_key = f.seller_key WHERE x.seller_key IS NULL)
        + (SELECT COUNT(*) FROM mart.fact_sales f LEFT JOIN mart.dim_location x ON x.location_key = f.location_key WHERE x.location_key IS NULL))::numeric
  UNION ALL SELECT 'SUM(net_amount) = clean.order_items net total',
         ROUND(ABS((SELECT COALESCE(SUM(net_amount),0) FROM mart.fact_sales)
                 - (SELECT COALESCE(SUM(mart.safe_num(net_amount)),0) FROM clean.order_items)))
  UNION ALL SELECT 'shipping fee total = per-order total (no double count)',
         ROUND(ABS((SELECT COALESCE(SUM(shipping_fee),0) FROM mart.fact_sales)
                 - (SELECT COALESCE(SUM(fee),0) FROM (
                      SELECT DISTINCT ON (s.order_id) COALESCE(mart.safe_num(s.shipping_fee),0) AS fee
                      FROM clean.shipping s WHERE s.order_id IN (SELECT order_id FROM mart.fact_sales)
                      ORDER BY s.order_id, s.shipment_id) q)))
  UNION ALL SELECT 'returned lines = valid returns on fact lines',
         ABS((SELECT COUNT(*) FROM (SELECT DISTINCT order_item_id FROM clean.returns
                                    WHERE lower(is_valid_return::text) IN ('true','1','t','yes')) r
              WHERE r.order_item_id IN (SELECT order_item_id FROM mart.fact_sales))
           - (SELECT COUNT(*) FROM mart.fact_sales WHERE is_returned))::numeric
  UNION ALL SELECT 'valid returns exist (0 returns = silent bug)',
         (CASE WHEN (SELECT COUNT(*) FROM mart.fact_sales WHERE is_returned) > 0 THEN 0 ELSE 1 END)::numeric
  UNION ALL SELECT 'lines with NULL cost',
         (SELECT COUNT(*) FROM mart.fact_sales WHERE cost_amount IS NULL)::numeric
  UNION ALL SELECT 'dimensions missing Unknown member (-1)',
         (5 - ((SELECT COUNT(*) FROM mart.dim_date WHERE date_key = -1) + (SELECT COUNT(*) FROM mart.dim_customer WHERE customer_key = -1)
             + (SELECT COUNT(*) FROM mart.dim_product WHERE product_key = -1) + (SELECT COUNT(*) FROM mart.dim_seller WHERE seller_key = -1)
             + (SELECT COUNT(*) FROM mart.dim_location WHERE location_key = -1)))::numeric
)
SELECT check_name, failed_rows, CASE WHEN failed_rows = 0 THEN 'PASS' ELSE 'FAIL' END AS status FROM c;
