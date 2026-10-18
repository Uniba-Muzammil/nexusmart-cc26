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

-- =====================================================================================
-- 15 BUSINESS QUESTIONS: views (playbook section 10). Batch 1 = sawal 1 se 5.
-- Sab views fact_sales par bani hain; NMV/refund/COGS ki definitions upar v_kpi_overall wali hi hain
-- (NMV = non-cancelled net_amount, refunds = non-cancelled valid-returned lines, COGS = kept lines).
-- =====================================================================================

-- Q1: Kaun si categories sab se zyada revenue aur margin deti hain
CREATE OR REPLACE VIEW mart.v_category_performance AS
WITH c AS (
  SELECT p.category,
         SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled)                                        AS nmv,
         COALESCE(SUM(f.returned_amount) FILTER (WHERE NOT f.is_cancelled AND f.is_returned), 0)    AS refunds,
         COALESCE(SUM(f.cost_amount) FILTER (WHERE NOT f.is_cancelled AND NOT f.is_returned), 0)    AS cogs_kept
  FROM mart.fact_sales f JOIN mart.dim_product p ON p.product_key = f.product_key
  GROUP BY p.category
)
SELECT RANK() OVER (ORDER BY (nmv - refunds) DESC)                   AS revenue_rank,
       category, nmv, refunds, nmv - refunds                         AS net_revenue,
       cogs_kept, (nmv - refunds) - cogs_kept                        AS margin,
       ((nmv - refunds) - cogs_kept) / NULLIF(nmv - refunds, 0)      AS margin_pct,
       RANK() OVER (ORDER BY ((nmv - refunds) - cogs_kept) DESC)     AS margin_rank
FROM c;

-- Q2a: Provinces (Unknown = ship city khali, delete nahi hui)
CREATE OR REPLACE VIEW mart.v_province_performance AS
WITH p AS (
  SELECT l.province, SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled) AS nmv
  FROM mart.fact_sales f JOIN mart.dim_location l ON l.location_key = f.location_key
  GROUP BY l.province
)
SELECT RANK() OVER (ORDER BY nmv DESC) AS nmv_rank, province, nmv,
       nmv / NULLIF(SUM(nmv) OVER (), 0) AS nmv_share
FROM p;

-- Q2b: Cities (ship city). Unknown (-1) ranking mein nahi, is liye shares ka total 100% se kam hai (farq = Unknown location)
CREATE OR REPLACE VIEW mart.v_city_performance AS
WITH c AS (
  SELECT l.location_key, l.city, l.province, SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled) AS nmv
  FROM mart.fact_sales f JOIN mart.dim_location l ON l.location_key = f.location_key
  WHERE f.location_key <> -1
  GROUP BY l.location_key, l.city, l.province
), t AS (
  SELECT SUM(net_amount) FILTER (WHERE NOT is_cancelled) AS total_nmv FROM mart.fact_sales
)
SELECT RANK() OVER (ORDER BY c.nmv DESC) AS nmv_rank, c.city, c.province, c.nmv,
       c.nmv / NULLIF(t.total_nmv, 0)    AS nmv_share
FROM c CROSS JOIN t;

-- Q2c: Top 5 cities ka share (ek row)
CREATE OR REPLACE VIEW mart.v_top5_city_share AS
SELECT SUM(nmv) AS top5_nmv, SUM(nmv_share) AS top5_share
FROM mart.v_city_performance WHERE nmv_rank <= 5;

-- Q3: Monthly revenue aur MoM growth (order window; v_kpi_monthly se)
CREATE OR REPLACE VIEW mart.v_monthly_revenue AS
SELECT year_num, month_num, year_num * 100 + month_num AS period, nmv, net_revenue, nmv_mom_growth AS mom_growth
FROM mart.v_kpi_monthly;

-- Q4: Return aur cancellation rate mahine ke hisaab se (order date ke mahine par)
CREATE OR REPLACE VIEW mart.v_rates_monthly AS
WITH m AS (
  SELECT d.year_num, d.month_num,
         COUNT(DISTINCT f.order_id)                                                   AS orders_all,
         COUNT(DISTINCT f.order_id) FILTER (WHERE f.is_cancelled)                     AS orders_cancelled,
         COUNT(*) FILTER (WHERE NOT f.is_cancelled AND f.order_status <> 'In Transit') AS delivered_lines,
         COUNT(*) FILTER (WHERE NOT f.is_cancelled AND f.order_status <> 'In Transit' AND f.is_returned) AS returned_lines
  FROM mart.fact_sales f JOIN mart.dim_date d ON d.date_key = f.date_key
  WHERE d.is_order_period
  GROUP BY d.year_num, d.month_num
)
SELECT year_num, month_num, year_num * 100 + month_num AS period,
       orders_all, orders_cancelled, orders_cancelled::numeric / NULLIF(orders_all, 0)       AS cancellation_rate,
       delivered_lines, returned_lines, returned_lines::numeric / NULLIF(delivered_lines, 0) AS return_rate
FROM m;

-- Q5: Gross vs Net revenue category ke hisaab se
-- gross_sales - cancelled_gross - discounts = nmv ; nmv - refunds = net_revenue
CREATE OR REPLACE VIEW mart.v_gross_vs_net_category AS
WITH c AS (
  SELECT p.category,
         SUM(f.gross_amount)                                                                    AS gross_sales,
         COALESCE(SUM(f.gross_amount)    FILTER (WHERE f.is_cancelled), 0)                      AS cancelled_gross,
         COALESCE(SUM(f.discount_amount) FILTER (WHERE NOT f.is_cancelled), 0)                 AS discounts,
         SUM(f.net_amount) FILTER (WHERE NOT f.is_cancelled)                                    AS nmv,
         COALESCE(SUM(f.returned_amount) FILTER (WHERE NOT f.is_cancelled AND f.is_returned), 0) AS refunds
  FROM mart.fact_sales f JOIN mart.dim_product p ON p.product_key = f.product_key
  GROUP BY p.category
)
SELECT category, gross_sales, cancelled_gross, discounts, nmv, refunds, nmv - refunds AS net_revenue,
       (nmv - refunds) / NULLIF(gross_sales, 0) AS net_to_gross_ratio
FROM c;
