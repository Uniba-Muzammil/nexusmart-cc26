-- Har check: expected vs actual. Koi FAIL ho to run_all.ps1 ruk jata hai.
WITH checks AS (
  SELECT 'fact rows = order_items (rejected orders ke baghair)' AS check_name,
         (SELECT COUNT(*) FROM staging.order_items oi JOIN staging.orders o USING (order_id))::numeric AS expected,
         (SELECT COUNT(*) FROM dw.fact_sales)::numeric AS actual
  UNION ALL SELECT 'duplicate order_item_id (0 honi chahiye)', 0,
         (SELECT COUNT(*) - COUNT(DISTINCT order_item_id) FROM dw.fact_sales)
  UNION ALL SELECT 'NULL keys in fact (0 honi chahiye)', 0,
         (SELECT COUNT(*) FROM dw.fact_sales WHERE date_key IS NULL OR customer_key IS NULL OR product_key IS NULL OR seller_key IS NULL OR location_key IS NULL)
  UNION ALL SELECT 'shipping fee total = per-order total',
         (SELECT COALESCE(SUM(dw.safe_num(shipping_fee)),0) FROM (SELECT DISTINCT ON (order_id) * FROM staging.shipping ORDER BY order_id, shipment_id) s
            WHERE order_id IN (SELECT order_id FROM staging.order_items GROUP BY order_id) AND order_id IN (SELECT order_id FROM staging.orders)),
         (SELECT ROUND(SUM(shipping_fee),0) FROM dw.fact_sales)
  UNION ALL SELECT 'returned lines = valid returns (matched lines)',
         (SELECT COUNT(*) FROM (SELECT DISTINCT order_item_id FROM staging.returns WHERE is_valid_return='True') r
            WHERE order_item_id IN (SELECT order_item_id FROM dw.fact_sales)),
         (SELECT COUNT(*) FROM dw.fact_sales WHERE is_returned)
  UNION ALL SELECT 'Unknown member in 5 dims', 5,
         (SELECT (SELECT COUNT(*) FROM dw.dim_date WHERE date_key=-1)+(SELECT COUNT(*) FROM dw.dim_customer WHERE customer_key=-1)
               + (SELECT COUNT(*) FROM dw.dim_product WHERE product_key=-1)+(SELECT COUNT(*) FROM dw.dim_seller WHERE seller_key=-1)
               + (SELECT COUNT(*) FROM dw.dim_location WHERE location_key=-1))
)
SELECT check_name, expected, actual, CASE WHEN ROUND(expected)=ROUND(actual) THEN 'PASS' ELSE 'FAIL' END AS status
FROM checks;

-- Sirf dekhne ke liye (fail nahi karte): kitni lines Unknown dimension par gayin
SELECT 'unknown customer lines' AS info, COUNT(*) FROM dw.fact_sales WHERE customer_key=-1
UNION ALL SELECT 'unknown product lines',  COUNT(*) FROM dw.fact_sales WHERE product_key=-1
UNION ALL SELECT 'unknown location lines', COUNT(*) FROM dw.fact_sales WHERE location_key=-1
UNION ALL SELECT 'unknown date lines',     COUNT(*) FROM dw.fact_sales WHERE date_key=-1;
