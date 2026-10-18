-- 05_metrics.sql : metric views (brief ki definitions, playbook section 9). D aur B inhi se numbers lete hain.
CREATE OR REPLACE VIEW mart.v_kpi_overall AS
WITH b AS (
  SELECT
    SUM(gross_amount)                                                            AS gross_sales,
    SUM(net_amount)       FILTER (WHERE NOT is_cancelled)                        AS nmv,
    COALESCE(SUM(returned_amount) FILTER (WHERE NOT is_cancelled AND is_returned), 0) AS refunds,
    SUM(cost_amount)      FILTER (WHERE NOT is_cancelled AND NOT is_returned)    AS cogs_kept,
    COUNT(DISTINCT order_id)                                                     AS orders_all,
    COUNT(DISTINCT order_id) FILTER (WHERE NOT is_cancelled)                     AS orders_non_cancelled,
    COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled)                         AS orders_cancelled,
    SUM(quantity)         FILTER (WHERE NOT is_cancelled)                        AS units,
    COUNT(DISTINCT customer_key) FILTER (WHERE NOT is_cancelled AND customer_key <> -1) AS active_customers,
    COUNT(*) FILTER (WHERE NOT is_cancelled AND order_status <> 'In Transit')    AS delivered_lines,
    COUNT(*) FILTER (WHERE NOT is_cancelled AND order_status <> 'In Transit' AND is_returned) AS returned_lines
  FROM mart.fact_sales
)
SELECT gross_sales, nmv, refunds, nmv - refunds AS net_revenue, cogs_kept,
       (nmv - refunds) - cogs_kept AS margin,
       ((nmv - refunds) - cogs_kept) / NULLIF(nmv - refunds, 0) AS margin_pct,
       orders_all, orders_non_cancelled, orders_cancelled,
       orders_cancelled::numeric / NULLIF(orders_all, 0)        AS cancellation_rate,
       nmv / NULLIF(orders_non_cancelled, 0)                    AS aov,
       units, active_customers, delivered_lines, returned_lines,
       returned_lines::numeric / NULLIF(delivered_lines, 0)     AS return_rate
FROM b;

-- Mahine ke hisaab se (order date ke mahine par; refunds bhi usi order ke mahine mein). Sirf order window.
CREATE OR REPLACE VIEW mart.v_kpi_monthly AS
WITH m AS (
  SELECT d.year_num, d.month_num,
         SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled)                                   AS nmv,
         COALESCE(SUM(f.returned_amount) FILTER (WHERE NOT f.is_cancelled AND f.is_returned),0) AS refunds,
         SUM(f.cost_amount) FILTER (WHERE NOT f.is_cancelled AND NOT f.is_returned)            AS cogs_kept,
         COUNT(DISTINCT f.order_id) FILTER (WHERE NOT f.is_cancelled)                          AS orders,
         COUNT(DISTINCT f.order_id) FILTER (WHERE f.is_cancelled)::numeric / COUNT(DISTINCT f.order_id) AS cancellation_rate
  FROM mart.fact_sales f JOIN mart.dim_date d ON d.date_key = f.date_key
  WHERE d.is_order_period
  GROUP BY d.year_num, d.month_num
)
SELECT year_num, month_num, nmv, refunds, nmv - refunds AS net_revenue, cogs_kept,
       (nmv - refunds) - cogs_kept AS margin, orders, cancellation_rate,
       nmv / NULLIF(LAG(nmv) OVER (ORDER BY year_num, month_num), 0) - 1 AS nmv_mom_growth
FROM m;

-- RFM segments ka size aur NMV
CREATE OR REPLACE VIEW mart.v_rfm_segments AS
SELECT c.segment, COUNT(DISTINCT c.customer_key) AS customers,
       SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled) AS nmv,
       SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled)
         / NULLIF(SUM(SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled)) OVER (), 0) AS nmv_share
FROM mart.dim_customer c
LEFT JOIN mart.fact_sales f ON f.customer_key = c.customer_key
WHERE c.customer_key <> -1
GROUP BY c.segment;

-- Kitni lines Unknown member par gayin (delete nahi hui, data quality report ke liye)
CREATE OR REPLACE VIEW mart.v_unknown_member_counts AS
SELECT 'unknown customer lines' AS item, COUNT(*) AS lines FROM mart.fact_sales WHERE customer_key = -1
UNION ALL SELECT 'unknown product lines',  COUNT(*) FROM mart.fact_sales WHERE product_key = -1
UNION ALL SELECT 'unknown seller lines',   COUNT(*) FROM mart.fact_sales WHERE seller_key = -1
UNION ALL SELECT 'unknown location lines (ship city khali)', COUNT(*) FROM mart.fact_sales WHERE location_key = -1
UNION ALL SELECT 'unknown date lines',     COUNT(*) FROM mart.fact_sales WHERE date_key = -1;
