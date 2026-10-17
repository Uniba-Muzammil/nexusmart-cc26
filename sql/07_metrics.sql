-- Brief ki metric definitions (PDF page 9). Power BI ke DAX se match karne ke liye.
CREATE OR REPLACE VIEW dw.v_kpi_overall AS
SELECT
  SUM(gross_amount - discount_amount) FILTER (WHERE NOT is_cancelled)                         AS nmv,
  SUM(returned_amount) FILTER (WHERE NOT is_cancelled AND is_returned)                        AS refunds,
  SUM(gross_amount - discount_amount) FILTER (WHERE NOT is_cancelled)
    - COALESCE(SUM(returned_amount) FILTER (WHERE NOT is_cancelled AND is_returned),0)        AS net_revenue,
  SUM(cost_amount) FILTER (WHERE NOT is_cancelled AND NOT is_returned)                        AS cogs_kept,
  SUM(gross_amount) AS gross_sales,
  COUNT(DISTINCT order_id) FILTER (WHERE NOT is_cancelled)                                    AS orders_non_cancelled,
  COUNT(DISTINCT order_id)                                                                    AS orders_all,
  COUNT(DISTINCT order_id) FILTER (WHERE is_cancelled)::numeric / COUNT(DISTINCT order_id)    AS cancellation_rate,
  SUM(gross_amount - discount_amount) FILTER (WHERE NOT is_cancelled)
    / NULLIF(COUNT(DISTINCT order_id) FILTER (WHERE NOT is_cancelled),0)                      AS aov,
  SUM(quantity) FILTER (WHERE NOT is_cancelled)                                               AS units,
  COUNT(*) FILTER (WHERE NOT is_cancelled AND is_returned)::numeric
    / NULLIF(COUNT(*) FILTER (WHERE NOT is_cancelled AND order_status <> 'In Transit'),0)     AS return_rate
FROM dw.fact_sales;

CREATE OR REPLACE VIEW dw.v_kpi_monthly AS
SELECT d.year_num, d.month_num,
  SUM(f.gross_amount - f.discount_amount) FILTER (WHERE NOT f.is_cancelled) AS nmv,
  COUNT(DISTINCT f.order_id) FILTER (WHERE NOT f.is_cancelled)              AS orders
FROM dw.fact_sales f JOIN dw.dim_date d USING (date_key)
GROUP BY 1,2 ORDER BY 1,2;
