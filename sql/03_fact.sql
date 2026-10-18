-- 03_fact.sql : FactSales (grain = ek order line item) + customer segment (RFM). Source = clean.*
-- Idempotent: truncate + insert, ek transaction mein.

-- Statistics: warna Postgres naye bhare tables par bura plan chunta hai aur yeh step minuton atak sakta hai
ANALYZE clean.orders;
ANALYZE clean.order_items;
ANALYZE clean.payments;
ANALYZE clean.shipping;
ANALYZE clean.returns;

BEGIN;
TRUNCATE mart.fact_sales;

WITH
-- Returns pehle per order_item aggregate (warna ek line ke 2 returns se fact ki row double ho jati). Sirf valid (non-Rejected)
ret AS (
  SELECT order_item_id,
         SUM(mart.safe_num(refund_amount))                  AS returned_amount,
         MIN(mart.safe_date(return_date))                   AS return_date,
         (ARRAY_AGG(return_reason ORDER BY return_date DESC, return_id DESC))[1] AS return_reason,
         (ARRAY_AGG(return_status ORDER BY return_date DESC, return_id DESC))[1] AS return_status
  FROM clean.returns
  WHERE lower(is_valid_return::text) IN ('true','1','t','yes')
  GROUP BY order_item_id
),
-- Payments: ek order ki ek row. Paid/Refunded ko Cancelled/Pending par tarjeeh, phir sab se nayi payment_date (playbook 3.4)
pay AS (
  SELECT DISTINCT ON (order_id) order_id, payment_method
  FROM clean.payments
  ORDER BY order_id,
           (lower(payment_status::text) IN ('paid','refunded')) DESC,
           mart.safe_date(payment_date) DESC NULLS LAST,
           payment_id
),
-- Shipping: order level, ek row per order. Shipping row na ho (cancelled) to fee 0
ship AS (
  SELECT DISTINCT ON (order_id) order_id,
         COALESCE(mart.safe_num(shipping_fee),0) AS fee,
         mart.safe_num(shipping_days)::int       AS shipping_days
  FROM clean.shipping
  ORDER BY order_id, shipment_id
),
lines AS (
  SELECT oi.order_item_id, oi.order_id, oi.product_id, oi.seller_id,
         mart.safe_num(oi.quantity)::int                                   AS quantity,
         mart.safe_num(oi.unit_price)                                      AS unit_price,
         mart.safe_num(oi.quantity) * mart.safe_num(oi.unit_price)         AS gross,
         COALESCE(mart.safe_num(oi.discount_amount),0)                     AS discount,
         mart.safe_num(oi.unit_cost) * mart.safe_num(oi.quantity)          AS cost
  FROM clean.order_items oi
),
alloc AS (   -- order ki shipping fee lines mein gross ke hisaab se baantna (sum per order = fee, double count nahi)
  SELECT l.*,
         CASE WHEN SUM(l.gross) OVER w > 0 THEN l.gross / SUM(l.gross) OVER w
              ELSE 1.0 / COUNT(*) OVER w END AS share
  FROM lines l
  WINDOW w AS (PARTITION BY l.order_id)
)
INSERT INTO mart.fact_sales
SELECT
  COALESCE(dd.date_key, -1),
  COALESCE(dc.customer_key, -1),
  COALESCE(dp.product_key, -1),
  COALESCE(ds.seller_key, -1),
  COALESCE(dl.location_key, -1),                       -- khali ship_city_id = -1 (playbook 3.4)
  a.order_id, a.order_item_id,
  a.quantity, a.unit_price,
  a.gross, a.discount, a.gross - a.discount, a.cost,
  COALESCE(sh.fee,0) * a.share,
  sh.shipping_days,
  (position('cancel' in lower(o.order_status::text)) = 1),
  (r.order_item_id IS NOT NULL),
  r.returned_amount,
  TO_CHAR(r.return_date,'YYYYMMDD')::int,
  r.return_reason, r.return_status,
  o.order_status, pay.payment_method, o.channel
FROM alloc a
JOIN clean.orders o                 ON o.order_id = a.order_id
LEFT JOIN mart.dim_customer dc      ON dc.customer_id = o.customer_id
LEFT JOIN mart.dim_product  dp      ON dp.product_id  = a.product_id
LEFT JOIN mart.dim_seller   ds      ON ds.seller_id   = a.seller_id
LEFT JOIN mart.dim_location dl      ON dl.city_id     = split_part(o.ship_city_id::text,'.',1)
LEFT JOIN mart.dim_date     dd      ON dd.full_date   = mart.safe_date(o.order_date)
LEFT JOIN ret r                     ON r.order_item_id = a.order_item_id
LEFT JOIN pay                       ON pay.order_id   = a.order_id
LEFT JOIN ship sh                   ON sh.order_id    = a.order_id;

-- RFM segment (playbook C3). Recency = 30 Jun 2025 tak din, Frequency = non-cancelled orders, Monetary = NMV.
-- Teeno par NTILE(5), 5 = behtar. Barabar values ko customer_key se tie-break kiya hai.
UPDATE mart.dim_customer SET segment = NULL WHERE customer_key <> -1;
WITH cust AS (
  SELECT f.customer_key,
         DATE '2025-06-30' - MAX(d.full_date) AS recency_days,
         COUNT(DISTINCT f.order_id)           AS freq,
         SUM(f.net_amount)                    AS monetary
  FROM mart.fact_sales f JOIN mart.dim_date d ON d.date_key = f.date_key
  WHERE NOT f.is_cancelled AND f.customer_key <> -1
  GROUP BY f.customer_key
), scored AS (
  SELECT customer_key,
         NTILE(5) OVER (ORDER BY recency_days DESC, customer_key) AS r,
         NTILE(5) OVER (ORDER BY freq, customer_key)              AS f,
         NTILE(5) OVER (ORDER BY monetary, customer_key)          AS m
  FROM cust
), seg AS (
  SELECT customer_key,
         CASE WHEN r >= 4 AND f >= 4 THEN 'Champions'
              WHEN r <= 2 AND f >= 3 THEN 'At Risk'
              WHEN f >= 4             THEN 'Loyal'
              WHEN r <= 2             THEN 'Lost'
              ELSE 'Potential' END AS segment
  FROM scored
)
UPDATE mart.dim_customer d SET segment = s.segment FROM seg s WHERE d.customer_key = s.customer_key;
UPDATE mart.dim_customer SET segment = 'No Orders' WHERE segment IS NULL AND customer_key <> -1;
COMMIT;

ANALYZE mart.fact_sales;
