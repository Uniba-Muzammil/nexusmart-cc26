CREATE SCHEMA IF NOT EXISTS clean;

CREATE TABLE IF NOT EXISTS clean.locations (
    city_id            INTEGER PRIMARY KEY,
    city               TEXT,
    province           TEXT,
    region             TEXT,
    latitude           NUMERIC(9,6),
    longitude          NUMERIC(9,6),
    population_tier    TEXT
);

CREATE TABLE IF NOT EXISTS clean.sellers (
    seller_id          TEXT PRIMARY KEY,
    seller_name        TEXT,
    join_date          DATE,
    seller_tier        TEXT,
    city_id            INTEGER,
    rating             NUMERIC(3,1)
);

CREATE TABLE IF NOT EXISTS clean.products (
    product_id         TEXT PRIMARY KEY,
    product_name       TEXT,
    category           TEXT,
    sub_category       TEXT,
    brand              TEXT,
    list_price         NUMERIC(14,2),
    cost_price         NUMERIC(14,2),
    weight_kg          NUMERIC(8,3),
    seller_id          TEXT,
    cost_imputed       SMALLINT
);

CREATE TABLE IF NOT EXISTS clean.product_map (
    product_id         TEXT PRIMARY KEY,
    master_id          TEXT,
    match_rule         TEXT
);

CREATE TABLE IF NOT EXISTS clean.customers (
    customer_id        TEXT PRIMARY KEY,
    full_name          TEXT,
    email              TEXT,
    phone              TEXT,
    gender             TEXT,
    registration_date  DATE,
    city_id            INTEGER,
    birth_year         INTEGER
);

CREATE TABLE IF NOT EXISTS clean.customer_map (
    customer_id        TEXT PRIMARY KEY,
    master_id          TEXT,
    match_rule         TEXT
);

CREATE TABLE IF NOT EXISTS clean.orders (
    order_id           TEXT PRIMARY KEY,
    customer_id        TEXT,
    customer_id_orig   TEXT,
    order_date         DATE,
    order_status       TEXT,
    ship_city_id       INTEGER,
    order_total        NUMERIC(14,2),
    discount_code      TEXT,
    discount_pct       NUMERIC(8,4),
    channel            TEXT,
    date_repair        TEXT,
    orphan_customer    SMALLINT,
    order_total_calc   NUMERIC(14,2)
);

CREATE TABLE IF NOT EXISTS clean.order_items (
    order_item_id      TEXT PRIMARY KEY,
    order_id           TEXT,
    product_id         TEXT,
    product_id_orig    TEXT,
    seller_id          TEXT,
    quantity           INTEGER,
    unit_price         NUMERIC(14,2),
    discount_amount    NUMERIC(14,2),
    gross_amount       NUMERIC(14,2),
    net_amount         NUMERIC(14,2),
    qty_fix            TEXT,
    price_fix          TEXT,
    orphan_product     SMALLINT,
    orphan_seller      SMALLINT,
    unit_cost          NUMERIC(14,2),
    cost_source        TEXT
);

CREATE TABLE IF NOT EXISTS clean.payments (
    payment_id         TEXT PRIMARY KEY,
    order_id           TEXT,
    payment_method     TEXT,
    payment_status     TEXT,
    amount             NUMERIC(14,2),
    payment_date       DATE,
    amount_fixed       SMALLINT,
    n_payments         SMALLINT,
    is_primary         SMALLINT
);

CREATE TABLE IF NOT EXISTS clean.shipping (
    shipment_id        TEXT PRIMARY KEY,
    order_id           TEXT,
    courier            TEXT,
    shipped_date       DATE,
    delivered_date     DATE,
    shipping_fee       NUMERIC(14,2),
    delivery_status    TEXT,
    shipping_days      INTEGER,
    date_fix           TEXT,
    fee_imputed        SMALLINT
);

CREATE TABLE IF NOT EXISTS clean.returns (
    return_id          TEXT PRIMARY KEY,
    order_item_id      TEXT,
    return_date        DATE,
    return_reason      TEXT,
    return_status      TEXT,
    refund_amount      NUMERIC(14,2),
    is_valid_return    SMALLINT,
    refund_fixed       SMALLINT,
    date_fixed         SMALLINT
);

