-- DimDate: 2024-01-01 se 2025-12-31 (return dates ke liye 2025 ke end tak). Events brief ke calendar se.
BEGIN;
TRUNCATE dw.fact_sales;
DELETE FROM dw.dim_date WHERE date_key <> -1;
INSERT INTO dw.dim_date
SELECT TO_CHAR(d,'YYYYMMDD')::INT, d::date,
       EXTRACT(DAY FROM d)::INT, EXTRACT(WEEK FROM d)::INT, EXTRACT(MONTH FROM d)::INT, TRIM(TO_CHAR(d,'Month')),
       EXTRACT(QUARTER FROM d)::INT, EXTRACT(YEAR FROM d)::INT, TRIM(TO_CHAR(d,'Day')),
       EXTRACT(ISODOW FROM d) IN (6,7),
       d::date BETWEEN '2024-03-11' AND '2024-04-09' OR d::date BETWEEN '2025-03-01' AND '2025-03-30',
       d::date BETWEEN '2024-04-10' AND '2024-04-12' OR d::date BETWEEN '2025-03-31' AND '2025-04-02',
       d::date BETWEEN '2024-06-17' AND '2024-06-19' OR d::date BETWEEN '2025-06-07' AND '2025-06-09',
       EXTRACT(MONTH FROM d)=8  AND EXTRACT(DAY FROM d)=14,
       EXTRACT(MONTH FROM d)=11 AND EXTRACT(DAY FROM d)=11,
       d::date = '2024-11-29'
FROM generate_series('2024-01-01'::date, '2025-12-31'::date, '1 day') AS d;
COMMIT;
