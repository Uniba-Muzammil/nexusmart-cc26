-- 02_dims.sql : 5 dimensions + FactSales ka table (sirf structure). Source = clean.* (B ka output).
-- Idempotent: dobara chalane par tables khali karke dobara bharti hain (views bachi rehti hain).
-- Note: is file ko akele chalana bhi theek hai, 01 ka intezar nahi.
CREATE SCHEMA IF NOT EXISTS mart;

-- Kharab date ya "Rs. 1,500" jaisi value par script girne ki bajaye NULL deta hai. Kisi bhi column type par chalte hain.
CREATE OR REPLACE FUNCTION mart.safe_date(t anyelement) RETURNS DATE LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF t IS NULL OR t::text !~ '^\d{4}-\d{2}-\d{2}' THEN RETURN NULL; END IF;
  RETURN left(t::text, 10)::date;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mart.safe_num(t anyelement) RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN NULLIF(regexp_replace(t::text, '[^0-9.\-]', '', 'g'), '')::numeric;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE TABLE IF NOT EXISTS mart.dim_date (
    date_key INT PRIMARY KEY, full_date DATE NOT NULL, day_of_month INT, week_of_year INT,
    month_num INT, month_name TEXT, quarter_num INT, year_num INT, day_name TEXT, is_weekend BOOLEAN,
    is_ramadan BOOLEAN, is_eid_ul_fitr BOOLEAN, is_eid_ul_adha BOOLEAN,
    is_14_august BOOLEAN, is_11_11 BOOLEAN, is_black_friday BOOLEAN,
    is_order_period BOOLEAN            -- true = 1 Jan 2024 se 30 Jun 2025 (order window). Baqi dates sirf return dates ke liye.
);
CREATE TABLE IF NOT EXISTS mart.dim_customer (
    customer_key INT PRIMARY KEY, customer_id TEXT, full_name TEXT, email TEXT, phone TEXT, gender TEXT,
    registration_date DATE, birth_year INT, segment TEXT, city TEXT, province TEXT, region TEXT
);
CREATE TABLE IF NOT EXISTS mart.dim_product (
    product_key INT PRIMARY KEY, product_id TEXT, product_name TEXT, category TEXT, sub_category TEXT,
    brand TEXT, list_price NUMERIC(12,2), weight_kg NUMERIC(8,3)
);
CREATE TABLE IF NOT EXISTS mart.dim_seller (
    seller_key INT PRIMARY KEY, seller_id TEXT, seller_name TEXT, join_date DATE, seller_tier TEXT,
    city TEXT, province TEXT, rating NUMERIC(5,2)
);
CREATE TABLE IF NOT EXISTS mart.dim_location (
    location_key INT PRIMARY KEY, city_id TEXT, city TEXT, province TEXT, region TEXT, population_tier TEXT
);
CREATE TABLE IF NOT EXISTS mart.fact_sales (
    date_key INT REFERENCES mart.dim_date(date_key),
    customer_key INT REFERENCES mart.dim_customer(customer_key),
    product_key INT REFERENCES mart.dim_product(product_key),
    seller_key INT REFERENCES mart.dim_seller(seller_key),
    location_key INT REFERENCES mart.dim_location(location_key),
    order_id TEXT, order_item_id TEXT PRIMARY KEY,
    quantity INT, unit_price NUMERIC(12,2),
    gross_amount NUMERIC(14,2), discount_amount NUMERIC(14,2), net_amount NUMERIC(14,2), cost_amount NUMERIC(14,2),
    shipping_fee NUMERIC(14,4), shipping_days INT,
    is_cancelled BOOLEAN, is_returned BOOLEAN, returned_amount NUMERIC(14,2),
    return_date_key INT, return_reason TEXT, return_status TEXT,
    order_status TEXT, payment_method TEXT, channel TEXT
);
-- Join tez karne ke liye (fact load natural key se join karta hai)
CREATE INDEX IF NOT EXISTS ix_dim_customer_id ON mart.dim_customer(customer_id);
CREATE INDEX IF NOT EXISTS ix_dim_product_id  ON mart.dim_product(product_id);
CREATE INDEX IF NOT EXISTS ix_dim_seller_id   ON mart.dim_seller(seller_id);
CREATE INDEX IF NOT EXISTS ix_dim_location_id ON mart.dim_location(city_id);
CREATE INDEX IF NOT EXISTS ix_dim_date_full   ON mart.dim_date(full_date);

BEGIN;
-- Ek hi statement mein sab khali (foreign keys ki wajah se fact bhi saath)
TRUNCATE mart.fact_sales, mart.dim_date, mart.dim_customer, mart.dim_product, mart.dim_seller, mart.dim_location;

-- Unknown member (key = -1) har dimension mein
INSERT INTO mart.dim_date     (date_key, full_date) VALUES (-1, '1900-01-01');
INSERT INTO mart.dim_customer (customer_key, customer_id, full_name, segment, city, province, region) VALUES (-1, 'UNKNOWN', 'Unknown', 'Unknown', 'Unknown', 'Unknown', 'Unknown');
INSERT INTO mart.dim_product  (product_key, product_id, product_name, category, sub_category, brand) VALUES (-1, 'UNKNOWN', 'Unknown', 'Unknown', 'Unknown', 'Unknown');
INSERT INTO mart.dim_seller   (seller_key, seller_id, seller_name, seller_tier, city, province) VALUES (-1, 'UNKNOWN', 'Unknown', 'Unknown', 'Unknown', 'Unknown');
INSERT INTO mart.dim_location VALUES (-1, 'UNKNOWN', 'Unknown', 'Unknown', 'Unknown', 'Unknown');

-- DimDate: 2024-01-01 se 2025-12-31. Valid order dates 30 Jun 2025 tak hain, lekin kuch returns uske baad ki hain,
-- is liye ReturnDateKey ke liye 2025 ke end tak. Festival dates = brief ka event calendar.
INSERT INTO mart.dim_date
SELECT TO_CHAR(d,'YYYYMMDD')::INT, d::date,
       EXTRACT(DAY FROM d)::INT, EXTRACT(WEEK FROM d)::INT, EXTRACT(MONTH FROM d)::INT, TRIM(TO_CHAR(d,'Month')),
       EXTRACT(QUARTER FROM d)::INT, EXTRACT(YEAR FROM d)::INT, TRIM(TO_CHAR(d,'Day')),
       EXTRACT(ISODOW FROM d) IN (6,7),
       d::date BETWEEN '2024-03-11' AND '2024-04-09' OR d::date BETWEEN '2025-03-01' AND '2025-03-30',
       d::date BETWEEN '2024-04-10' AND '2024-04-12' OR d::date BETWEEN '2025-03-31' AND '2025-04-02',
       d::date BETWEEN '2024-06-17' AND '2024-06-19' OR d::date BETWEEN '2025-06-07' AND '2025-06-09',
       EXTRACT(MONTH FROM d)=8  AND EXTRACT(DAY FROM d)=14,
       EXTRACT(MONTH FROM d)=11 AND EXTRACT(DAY FROM d)=11,
       d::date = '2024-11-29',
       d::date <= '2025-06-30'
FROM generate_series('2024-01-01'::date, '2025-12-31'::date, '1 day') AS d;

-- DimLocation: city_id natural key (float jaise 614.0 ho to bhi theek)
INSERT INTO mart.dim_location (location_key, city_id, city, province, region, population_tier)
SELECT ROW_NUMBER() OVER (ORDER BY mart.safe_num(city_id)), split_part(city_id::text,'.',1),
       TRIM(city), TRIM(province), TRIM(region), TRIM(population_tier)
FROM clean.locations;

-- DimCustomer: sirf master customers (duplicates cleaning ne merge kar diye). City/province/region customer ki registered city se.
-- Segment (RFM) 03_fact.sql ke aakhir mein bharta hai.
INSERT INTO mart.dim_customer (customer_key, customer_id, full_name, email, phone, gender, registration_date,
                               birth_year, segment, city, province, region)
SELECT ROW_NUMBER() OVER (ORDER BY c.customer_id), c.customer_id, TRIM(c.full_name), c.email, c.phone, c.gender,
       mart.safe_date(c.registration_date), mart.safe_num(c.birth_year)::int, NULL,
       COALESCE(l.city,'Unknown'), COALESCE(l.province,'Unknown'), COALESCE(l.region,'Unknown')
FROM clean.customers c
LEFT JOIN mart.dim_location l ON l.city_id = split_part(c.city_id::text,'.',1) AND l.location_key <> -1;

INSERT INTO mart.dim_product (product_key, product_id, product_name, category, sub_category, brand, list_price, weight_kg)
SELECT ROW_NUMBER() OVER (ORDER BY product_id), product_id, TRIM(product_name), TRIM(category), TRIM(sub_category), TRIM(brand),
       mart.safe_num(list_price), CASE WHEN mart.safe_num(weight_kg) > 0 THEN mart.safe_num(weight_kg) END
FROM clean.products;

INSERT INTO mart.dim_seller (seller_key, seller_id, seller_name, join_date, seller_tier, city, province, rating)
SELECT ROW_NUMBER() OVER (ORDER BY s.seller_id), s.seller_id, TRIM(s.seller_name), mart.safe_date(s.join_date), TRIM(s.seller_tier),
       COALESCE(l.city,'Unknown'), COALESCE(l.province,'Unknown'),
       CASE WHEN mart.safe_num(s.rating) BETWEEN 0 AND 5 THEN mart.safe_num(s.rating) END
FROM clean.sellers s
LEFT JOIN mart.dim_location l ON l.city_id = split_part(s.city_id::text,'.',1) AND l.location_key <> -1;
COMMIT;

ANALYZE mart.dim_date;
ANALYZE mart.dim_customer;
ANALYZE mart.dim_product;
ANALYZE mart.dim_seller;
ANALYZE mart.dim_location;
