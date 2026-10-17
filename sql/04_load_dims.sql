-- 4 dimensions (DimDate 03 mein). Har run par pehle fact khali, phir dims khali + dobara bhare (idempotent).
BEGIN;
TRUNCATE dw.fact_sales;
DELETE FROM dw.dim_customer WHERE customer_key <> -1;
DELETE FROM dw.dim_product  WHERE product_key  <> -1;
DELETE FROM dw.dim_seller   WHERE seller_key   <> -1;
DELETE FROM dw.dim_location WHERE location_key <> -1;

-- DimLocation: city_id hi natural key
INSERT INTO dw.dim_location (location_key, city_id, city, province, region, population_tier)
SELECT ROW_NUMBER() OVER (ORDER BY split_part(city_id,'.',1)::int),
       split_part(city_id,'.',1), TRIM(city), TRIM(province), TRIM(region), TRIM(population_tier)
FROM staging.locations;

-- DimCustomer: sirf master customers (duplicates cleaning ne merge kar diye). City/province yahin copy (snowflake nahi)
INSERT INTO dw.dim_customer (customer_key, customer_id, full_name, email, phone, gender, registration_date,
                             birth_year, segment, city, province)
SELECT ROW_NUMBER() OVER (ORDER BY c.customer_id),
       c.customer_id, TRIM(c.full_name), c.email, c.phone, c.gender,
       dw.safe_date(c.registration_date),
       dw.safe_num(c.birth_year)::int,
       NULL,                      -- segment: BI mein RFM se banega
       l.city, l.province
FROM staging.customers c
LEFT JOIN dw.dim_location l ON l.city_id = split_part(c.city_id,'.',1);

-- DimProduct
INSERT INTO dw.dim_product (product_key, product_id, product_name, category, sub_category, brand, list_price, weight_kg)
SELECT ROW_NUMBER() OVER (ORDER BY product_id),
       product_id, TRIM(product_name), TRIM(category), TRIM(sub_category), TRIM(brand),
       dw.safe_num(list_price),
       CASE WHEN dw.safe_num(weight_kg) > 0 THEN dw.safe_num(weight_kg) END
FROM staging.products;

-- DimSeller
INSERT INTO dw.dim_seller (seller_key, seller_id, seller_name, join_date, seller_tier, city, province, rating)
SELECT ROW_NUMBER() OVER (ORDER BY s.seller_id),
       s.seller_id, TRIM(s.seller_name), dw.safe_date(s.join_date), TRIM(s.seller_tier),
       l.city, l.province, CASE WHEN dw.safe_num(s.rating) BETWEEN 0 AND 5 THEN dw.safe_num(s.rating) END
FROM staging.sellers s
LEFT JOIN dw.dim_location l ON l.city_id = split_part(s.city_id,'.',1);
COMMIT;
