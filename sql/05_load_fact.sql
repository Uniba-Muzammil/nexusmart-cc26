-- FactSales: grain = ek order line (order_item). Idempotent: truncate + insert.
BEGIN;
TRUNCATE dw.fact_sales;

WITH
-- returns: pehle per order_item aggregate (warna fact ki grain toot jati hai). Sirf valid (non-Rejected) returns
ret AS (
  SELECT order_item_id,
         SUM(dw.safe_num(refund_amount))          AS returned_amount,
         MIN(dw.safe_date(return_date))               AS return_date,
         (ARRAY_AGG(return_reason ORDER BY return_date DESC, return_id DESC))[1] AS return_reason,
         (ARRAY_AGG(return_status ORDER BY return_date DESC, return_id DESC))[1] AS return_status
  FROM staging.returns
  WHERE is_valid_return = 'True'
  GROUP BY order_item_id
),
-- payments: ek order ki ek row (Paid ko tarjeeh, phir latest)
pay AS (
  SELECT DISTINCT ON (order_id) order_id, payment_method
  FROM staging.payments
  ORDER BY order_id, (payment_status = 'Paid') DESC, payment_date DESC NULLS LAST, payment_id
),
-- order-level shipping: ek row per order
ship AS (
  SELECT DISTINCT ON (order_id) order_id,
         COALESCE(dw.safe_num(shipping_fee),0) AS fee,
         dw.safe_num(shipping_days)::int       AS shipping_days
  FROM staging.shipping
  ORDER BY order_id, shipment_id
),
lines AS (
  SELECT oi.order_item_id, oi.order_id,
         COALESCE(pm.master_id, oi.product_id) AS product_id,
         oi.seller_id,
         dw.safe_num(oi.quantity)::int          AS quantity,
         dw.safe_num(oi.unit_price)             AS unit_price,
         dw.safe_num(oi.quantity) * dw.safe_num(oi.unit_price) AS gross,
         COALESCE(dw.safe_num(oi.discount_amount),0) AS discount,
         dw.safe_num(oi.cost_price) * dw.safe_num(oi.quantity) AS cost
  FROM staging.order_items oi
  LEFT JOIN staging.product_map pm ON pm.dup_id = oi.product_id
),
alloc AS (   -- order ki shipping fee lines mein gross ke hisaab se baantna (double count nahi)
  SELECT l.*,
         CASE WHEN SUM(l.gross) OVER w > 0
              THEN l.gross / SUM(l.gross) OVER w
              ELSE 1.0 / COUNT(*) OVER w END AS share
  FROM lines l
  WINDOW w AS (PARTITION BY l.order_id)
)
INSERT INTO dw.fact_sales
SELECT
  COALESCE(dd.date_key, -1),
  COALESCE(dc.customer_key, -1),
  COALESCE(dp.product_key, -1),
  COALESCE(ds.seller_key, -1),
  COALESCE(dl.location_key, -1),
  a.order_id, a.order_item_id,
  a.quantity, a.unit_price,
  a.gross, a.discount, a.gross - a.discount, a.cost,
  COALESCE(sh.fee,0) * a.share,
  sh.shipping_days,
  (o.order_status ILIKE 'cancel%'),
  (r.order_item_id IS NOT NULL),
  r.returned_amount,
  TO_CHAR(r.return_date,'YYYYMMDD')::int,
  r.return_reason, r.return_status,
  o.order_status, pay.payment_method, o.channel
FROM alloc a
JOIN staging.orders o               ON o.order_id = a.order_id          -- rejected orders ki lines bahar
LEFT JOIN staging.customer_map cm   ON cm.dup_id = o.customer_id
LEFT JOIN dw.dim_customer dc        ON dc.customer_id = COALESCE(cm.master_id, o.customer_id)
LEFT JOIN dw.dim_product  dp        ON dp.product_id  = a.product_id
LEFT JOIN dw.dim_seller   ds        ON ds.seller_id   = a.seller_id
LEFT JOIN dw.dim_location dl        ON dl.city_id     = split_part(o.ship_city_id,'.',1)
LEFT JOIN dw.dim_date     dd        ON dd.full_date   = dw.safe_date(o.order_date)
LEFT JOIN ret r                     ON r.order_item_id = a.order_item_id
LEFT JOIN pay                       ON pay.order_id   = a.order_id
LEFT JOIN ship sh                   ON sh.order_id    = a.order_id;
COMMIT;
