-- EXAMPLE for Person C: FactSales at ORDER-LINE grain built from the clean tables.
-- Adapt column names to the playbook. Every join below is 1-to-1 or pre-aggregated, so the row count stays = clean.order_items.
CREATE OR REPLACE VIEW clean.v_fact_sales AS
SELECT
    i.order_item_id,
    i.order_id,
    o.order_date,
    CASE WHEN o.orphan_customer = 1 THEN '-1' ELSE o.customer_id END      AS customer_key,   -- already the MASTER id
    CASE WHEN i.orphan_product  = 1 THEN '-1' ELSE i.product_id  END      AS product_key,
    CASE WHEN i.orphan_seller   = 1 THEN '-1' ELSE i.seller_id   END      AS seller_key,
    COALESCE(o.ship_city_id, -1)                                          AS location_key,
    o.order_status, o.channel,
    p.payment_method, p.payment_status,                                    -- from the ONE primary payment row
    i.quantity, i.unit_price,
    i.gross_amount, i.discount_amount, i.net_amount,                       -- net_amount = revenue of the line
    i.unit_cost * i.quantity                                              AS cost_amount,    -- NOT products.cost_price
    i.cost_source,                                                         -- filter on it if you want "genuine cost only"
    s.courier, s.shipping_days,
    s.shipping_fee * i.gross_amount
        / NULLIF(SUM(i.gross_amount) OVER (PARTITION BY i.order_id), 0)   AS shipping_fee_alloc, -- order fee spread by gross share
    COALESCE(r.refund_amount, 0)                                          AS refund_amount,
    COALESCE(r.return_count, 0)                                           AS valid_return_count
FROM clean.order_items i
JOIN clean.orders o                 ON o.order_id = i.order_id
LEFT JOIN clean.payments p          ON p.order_id = i.order_id AND p.is_primary = 1
LEFT JOIN clean.shipping s          ON s.order_id = i.order_id
LEFT JOIN (SELECT order_item_id,
                  SUM(refund_amount) AS refund_amount,
                  COUNT(*)           AS return_count
           FROM clean.returns
           WHERE is_valid_return = 1                                       -- status 'Rejected' is NOT a return
           GROUP BY order_item_id) r ON r.order_item_id = i.order_item_id;
