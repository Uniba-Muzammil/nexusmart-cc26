-- Dobara chalane par error nahi aata (idempotent)
DROP VIEW IF EXISTS dw.v_kpi_overall;
DROP VIEW IF EXISTS dw.v_kpi_monthly;
DROP TABLE IF EXISTS dw.fact_sales;
DROP TABLE IF EXISTS dw.dim_date;
DROP TABLE IF EXISTS dw.dim_customer;
DROP TABLE IF EXISTS dw.dim_product;
DROP TABLE IF EXISTS dw.dim_seller;
DROP TABLE IF EXISTS dw.dim_location;

CREATE TABLE dw.dim_date (
    date_key INT PRIMARY KEY, full_date DATE NOT NULL, day_of_month INT, week_of_year INT,
    month_num INT, month_name TEXT, quarter_num INT, year_num INT, day_name TEXT, is_weekend BOOLEAN,
    is_ramadan BOOLEAN, is_eid_ul_fitr BOOLEAN, is_eid_ul_adha BOOLEAN,
    is_14_august BOOLEAN, is_11_11 BOOLEAN, is_black_friday BOOLEAN
);
CREATE TABLE dw.dim_customer (
    customer_key INT PRIMARY KEY, customer_id TEXT, full_name TEXT, email TEXT, phone TEXT, gender TEXT,
    registration_date DATE, birth_year INT, segment TEXT, city TEXT, province TEXT
);
CREATE TABLE dw.dim_product (
    product_key INT PRIMARY KEY, product_id TEXT, product_name TEXT, category TEXT, sub_category TEXT,
    brand TEXT, list_price NUMERIC(12,2), weight_kg NUMERIC(8,3)
);
CREATE TABLE dw.dim_seller (
    seller_key INT PRIMARY KEY, seller_id TEXT, seller_name TEXT, join_date DATE, seller_tier TEXT,
    city TEXT, province TEXT, rating NUMERIC(5,2)
);
CREATE TABLE dw.dim_location (
    location_key INT PRIMARY KEY, city_id TEXT, city TEXT, province TEXT, region TEXT, population_tier TEXT
);
CREATE TABLE dw.fact_sales (
    date_key INT REFERENCES dw.dim_date(date_key),
    customer_key INT REFERENCES dw.dim_customer(customer_key),
    product_key INT REFERENCES dw.dim_product(product_key),
    seller_key INT REFERENCES dw.dim_seller(seller_key),
    location_key INT REFERENCES dw.dim_location(location_key),
    order_id TEXT, order_item_id TEXT PRIMARY KEY,
    quantity INT, unit_price NUMERIC(12,2),
    gross_amount NUMERIC(14,2), discount_amount NUMERIC(14,2), net_amount NUMERIC(14,2), cost_amount NUMERIC(14,2),
    shipping_fee NUMERIC(14,4), shipping_days INT,
    is_cancelled BOOLEAN, is_returned BOOLEAN, returned_amount NUMERIC(14,2),
    return_date_key INT, return_reason TEXT, return_status TEXT,
    order_status TEXT, payment_method TEXT, channel TEXT
);

-- Unknown member (key = -1) har dimension mein
INSERT INTO dw.dim_date     (date_key, full_date) VALUES (-1, '1900-01-01');
INSERT INTO dw.dim_customer (customer_key, customer_id, full_name) VALUES (-1, 'UNKNOWN', 'Unknown');
INSERT INTO dw.dim_product  (product_key, product_id, product_name, category) VALUES (-1, 'UNKNOWN', 'Unknown', 'Unknown');
INSERT INTO dw.dim_seller   (seller_key, seller_id, seller_name) VALUES (-1, 'UNKNOWN', 'Unknown');
INSERT INTO dw.dim_location VALUES (-1, 'UNKNOWN', 'Unknown', 'Unknown', 'Unknown', 'Unknown');
