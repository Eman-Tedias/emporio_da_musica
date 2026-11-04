DROP FUNCTION IF EXISTS get_authorized_order(INT, TEXT, TEXT);
DROP TABLE IF EXISTS order_items, orders, promotions, products, categories, customers CASCADE;

CREATE TABLE categories (
    category_id  INT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT
);

CREATE TABLE products (
    product_id      INT PRIMARY KEY,
    category_id     INT NOT NULL REFERENCES categories(category_id),
    name            TEXT NOT NULL,
    description     TEXT,
    price_brl       NUMERIC(10,2) NOT NULL CHECK (price_brl >= 0),
    stock_quantity  INT NOT NULL CHECK (stock_quantity >= 0),
    status          TEXT NOT NULL CHECK (status IN ('active', 'discontinued', 'coming_soon')),
    specs           JSONB,
    created_at      DATE
);

CREATE TABLE promotions (
    promotion_id      INT PRIMARY KEY,
    product_id        INT NOT NULL REFERENCES products(product_id),
    discount_percent  NUMERIC(5,2) NOT NULL CHECK (discount_percent > 0 AND discount_percent <= 100),
    description       TEXT,
    is_active         BOOLEAN NOT NULL
);

CREATE TABLE customers (
    customer_id   INT PRIMARY KEY,
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL,
    phone_digits  TEXT NOT NULL CHECK (phone_digits ~ '^[0-9]{10,11}$'),
    email         TEXT NOT NULL CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    city          TEXT
);

CREATE TABLE orders (
    order_id            INT PRIMARY KEY,
    customer_id         INT NOT NULL REFERENCES customers(customer_id),
    order_date          DATE NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')),
    total_brl           NUMERIC(10,2) NOT NULL CHECK (total_brl >= 0),
    payment_method      TEXT NOT NULL CHECK (payment_method ~ '^(pix|debit|boleto|credit_[0-9]{1,2}x)$'),
    tracking_code       TEXT CHECK (tracking_code ~ '^BR[A-Z0-9]{9}BR$'),
    estimated_delivery  DATE,
    notes               TEXT
);

CREATE TABLE order_items (
    order_id    INT NOT NULL REFERENCES orders(order_id),
    product_id  INT NOT NULL REFERENCES products(product_id),
    quantity    INT NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (order_id, product_id)
);

CREATE FUNCTION get_authorized_order(p_order_id INT, p_email TEXT, p_phone_digits TEXT)
RETURNS TABLE (
    order_id INT, order_date DATE, status TEXT, total_brl NUMERIC,
    payment_method TEXT, tracking_code TEXT, estimated_delivery DATE,
    notes TEXT, items JSONB
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    SELECT o.order_id, o.order_date, o.status, o.total_brl, o.payment_method,
           o.tracking_code, o.estimated_delivery, o.notes,
           (SELECT jsonb_agg(jsonb_build_object('product', p.name, 'quantity', i.quantity))
              FROM order_items i JOIN products p ON p.product_id = i.product_id
             WHERE i.order_id = o.order_id)
      FROM orders o
      JOIN customers c ON c.customer_id = o.customer_id
     WHERE o.order_id = p_order_id
       AND (lower(c.email) = lower(p_email) OR c.phone_digits = p_phone_digits);
$$;

REVOKE SELECT ON customers, orders, order_items FROM agent_reader;
REVOKE ALL ON FUNCTION get_authorized_order(INT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_authorized_order(INT, TEXT, TEXT) TO agent_reader;