-- Relational schema. Money is stored as integer minor units (cents). Timestamps are UTC text.
-- Safe to run repeatedly (IF NOT EXISTS). Foreign keys are enforced per-connection (PRAGMA in db.py).

CREATE TABLE IF NOT EXISTS roles (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  permissions TEXT NOT NULL DEFAULT ''          -- comma list; '*' = everything
);

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  name          TEXT NOT NULL DEFAULT '',
  role_id       INTEGER NOT NULL REFERENCES roles(id),
  is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  last_login_at TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
  email      TEXT NOT NULL COLLATE NOCASE,
  first_name TEXT NOT NULL DEFAULT '',
  last_name  TEXT NOT NULL DEFAULT '',
  phone      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);

CREATE TABLE IF NOT EXISTS addresses (
  id          INTEGER PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  label       TEXT NOT NULL DEFAULT '',
  full_name   TEXT NOT NULL,
  line1       TEXT NOT NULL,
  line2       TEXT NOT NULL DEFAULT '',
  city        TEXT NOT NULL,
  region      TEXT NOT NULL DEFAULT '',
  postal_code TEXT NOT NULL DEFAULT '',
  country     TEXT NOT NULL,
  phone       TEXT NOT NULL DEFAULT '',
  is_default  INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_addresses_customer ON addresses(customer_id);

CREATE TABLE IF NOT EXISTS categories (
  id          INTEGER PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  image       TEXT NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 0,
  is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

CREATE TABLE IF NOT EXISTS collections (
  id          INTEGER PRIMARY KEY,
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  image       TEXT NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 0,
  is_featured INTEGER NOT NULL DEFAULT 0 CHECK (is_featured IN (0,1)),
  is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

CREATE TABLE IF NOT EXISTS products (
  id               INTEGER PRIMARY KEY,
  slug             TEXT NOT NULL UNIQUE,
  name             TEXT NOT NULL,
  description      TEXT NOT NULL DEFAULT '',
  details          TEXT NOT NULL DEFAULT '',            -- materials / care
  category_id      INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  price_cents      INTEGER NOT NULL CHECK (price_cents >= 0),
  sale_price_cents INTEGER CHECK (sale_price_cents IS NULL OR (sale_price_cents >= 0 AND sale_price_cents < price_cents)),
  is_featured      INTEGER NOT NULL DEFAULT 0 CHECK (is_featured IN (0,1)),
  is_published     INTEGER NOT NULL DEFAULT 0 CHECK (is_published IN (0,1)),
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_products_category  ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_published ON products(is_published, created_at);

CREATE TABLE IF NOT EXISTS product_collections (
  product_id    INTEGER NOT NULL REFERENCES products(id)    ON DELETE CASCADE,
  collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  PRIMARY KEY (product_id, collection_id)
);
CREATE INDEX IF NOT EXISTS idx_pc_collection ON product_collections(collection_id);

CREATE TABLE IF NOT EXISTS product_images (
  id         INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  filename   TEXT NOT NULL,
  alt        TEXT NOT NULL DEFAULT '',
  position   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_images_product ON product_images(product_id, position);

-- Variants double as the inventory record: `stock` is the on-hand quantity and can never go negative.
CREATE TABLE IF NOT EXISTS product_variants (
  id                  INTEGER PRIMARY KEY,
  product_id          INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  sku                 TEXT NOT NULL UNIQUE,
  size                TEXT NOT NULL DEFAULT '',
  color               TEXT NOT NULL DEFAULT '',
  color_hex           TEXT NOT NULL DEFAULT '',
  stock               INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
  low_stock_threshold INTEGER NOT NULL DEFAULT 3 CHECK (low_stock_threshold >= 0),
  is_active           INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  UNIQUE (product_id, size, color)
);
CREATE INDEX IF NOT EXISTS idx_variants_product ON product_variants(product_id);

-- Append-only ledger of every stock change. Snapshots survive product/variant deletion.
CREATE TABLE IF NOT EXISTS inventory_movements (
  id           INTEGER PRIMARY KEY,
  variant_id   INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
  sku          TEXT NOT NULL DEFAULT '',
  product_name TEXT NOT NULL DEFAULT '',
  variant_desc TEXT NOT NULL DEFAULT '',
  delta        INTEGER NOT NULL,
  stock_after  INTEGER NOT NULL,
  reason       TEXT NOT NULL,           -- initial | restock | correction | damaged | order | order_cancelled | admin_edit
  note         TEXT NOT NULL DEFAULT '',
  order_id     INTEGER,                 -- informational (no FK so history survives order purges)
  user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_moves_variant ON inventory_movements(variant_id, id);
CREATE INDEX IF NOT EXISTS idx_moves_created ON inventory_movements(created_at);

CREATE TABLE IF NOT EXISTS shipping_methods (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  description     TEXT NOT NULL DEFAULT '',
  price_cents     INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
  free_over_cents INTEGER CHECK (free_over_cents IS NULL OR free_over_cents >= 0),
  sort_order      INTEGER NOT NULL DEFAULT 0,
  is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

CREATE TABLE IF NOT EXISTS discounts (
  id                 INTEGER PRIMARY KEY,
  code               TEXT NOT NULL UNIQUE COLLATE NOCASE,
  kind               TEXT NOT NULL CHECK (kind IN ('percent','fixed')),
  value              INTEGER NOT NULL CHECK (value > 0),     -- percent (1-100) or cents
  min_subtotal_cents INTEGER NOT NULL DEFAULT 0,
  max_uses           INTEGER CHECK (max_uses IS NULL OR max_uses > 0),
  used_count         INTEGER NOT NULL DEFAULT 0,
  starts_on          TEXT,                                   -- YYYY-MM-DD
  ends_on            TEXT,
  is_active          INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS carts (
  id                 INTEGER PRIMARY KEY,
  token              TEXT NOT NULL UNIQUE,
  customer_id        INTEGER REFERENCES customers(id) ON DELETE SET NULL,
  discount_code      TEXT NOT NULL DEFAULT '',
  shipping_method_id INTEGER REFERENCES shipping_methods(id) ON DELETE SET NULL,
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_carts_customer ON carts(customer_id);

CREATE TABLE IF NOT EXISTS cart_items (
  id         INTEGER PRIMARY KEY,
  cart_id    INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
  variant_id INTEGER NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
  quantity   INTEGER NOT NULL CHECK (quantity > 0),
  UNIQUE (cart_id, variant_id)
);

CREATE TABLE IF NOT EXISTS orders (
  id                 INTEGER PRIMARY KEY,
  number             TEXT NOT NULL UNIQUE,
  customer_id        INTEGER REFERENCES customers(id) ON DELETE SET NULL,
  email              TEXT NOT NULL,
  phone              TEXT NOT NULL DEFAULT '',
  status             TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','confirmed','processing','shipped','delivered','cancelled','refunded')),
  payment_status     TEXT NOT NULL DEFAULT 'unpaid'
                     CHECK (payment_status IN ('unpaid','paid','failed','refunded')),
  payment_method     TEXT NOT NULL DEFAULT '',
  payment_provider   TEXT NOT NULL DEFAULT '',
  currency           TEXT NOT NULL DEFAULT 'EUR',
  subtotal_cents     INTEGER NOT NULL CHECK (subtotal_cents >= 0),
  discount_cents     INTEGER NOT NULL DEFAULT 0 CHECK (discount_cents >= 0),
  discount_code      TEXT NOT NULL DEFAULT '',
  shipping_cents     INTEGER NOT NULL DEFAULT 0 CHECK (shipping_cents >= 0),
  shipping_method    TEXT NOT NULL DEFAULT '',
  tax_cents          INTEGER NOT NULL DEFAULT 0 CHECK (tax_cents >= 0),
  tax_inclusive      INTEGER NOT NULL DEFAULT 0,
  total_cents        INTEGER NOT NULL CHECK (total_cents >= 0),
  ship_name          TEXT NOT NULL,
  ship_line1         TEXT NOT NULL,
  ship_line2         TEXT NOT NULL DEFAULT '',
  ship_city          TEXT NOT NULL,
  ship_region        TEXT NOT NULL DEFAULT '',
  ship_postal        TEXT NOT NULL DEFAULT '',
  ship_country       TEXT NOT NULL,
  carrier            TEXT NOT NULL DEFAULT '',
  tracking_number    TEXT NOT NULL DEFAULT '',
  customer_note      TEXT NOT NULL DEFAULT '',
  admin_note         TEXT NOT NULL DEFAULT '',
  access_token       TEXT NOT NULL,                 -- lets guests view their own order
  idempotency_key    TEXT UNIQUE,                   -- blocks duplicate submissions
  stock_released     INTEGER NOT NULL DEFAULT 0,    -- 1 once reserved stock has been returned
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_email    ON orders(email);

-- Snapshot rows: name/price/variant are copied at purchase time. Product/variant links are
-- nullable so deleting a catalog item never alters or destroys order history.
CREATE TABLE IF NOT EXISTS order_items (
  id                  INTEGER PRIMARY KEY,
  order_id            INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id          INTEGER REFERENCES products(id) ON DELETE SET NULL,
  variant_id          INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
  product_name        TEXT NOT NULL,
  sku                 TEXT NOT NULL DEFAULT '',
  size                TEXT NOT NULL DEFAULT '',
  color               TEXT NOT NULL DEFAULT '',
  image               TEXT NOT NULL DEFAULT '',
  unit_price_cents    INTEGER NOT NULL CHECK (unit_price_cents >= 0),
  compare_price_cents INTEGER NOT NULL DEFAULT 0,
  quantity            INTEGER NOT NULL CHECK (quantity > 0),
  line_total_cents    INTEGER NOT NULL CHECK (line_total_cents >= 0)
);
CREATE INDEX IF NOT EXISTS idx_items_order   ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product ON order_items(product_id);

CREATE TABLE IF NOT EXISTS order_status_history (
  id          INTEGER PRIMARY KEY,
  order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  from_status TEXT,
  to_status   TEXT NOT NULL,
  note        TEXT NOT NULL DEFAULT '',
  user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_history_order ON order_status_history(order_id);

CREATE TABLE IF NOT EXISTS payments (
  id             INTEGER PRIMARY KEY,
  order_id       INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  provider       TEXT NOT NULL,
  provider_ref   TEXT NOT NULL DEFAULT '',
  method         TEXT NOT NULL DEFAULT '',
  amount_cents   INTEGER NOT NULL CHECK (amount_cents >= 0),
  currency       TEXT NOT NULL DEFAULT 'EUR',
  status         TEXT NOT NULL CHECK (status IN ('pending','succeeded','failed','refunded')),
  is_simulated   INTEGER NOT NULL DEFAULT 0,
  failure_reason TEXT NOT NULL DEFAULT '',
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);
-- At most one successful (or later refunded) charge per order => no double payment.
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_one_success
  ON payments(order_id) WHERE status IN ('succeeded','refunded');

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,                       -- JSON
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pages (                -- editable policy / info pages
  slug           TEXT PRIMARY KEY,
  title          TEXT NOT NULL,
  body           TEXT NOT NULL DEFAULT '',
  show_in_footer INTEGER NOT NULL DEFAULT 1,
  sort_order     INTEGER NOT NULL DEFAULT 0,
  updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
  id         INTEGER PRIMARY KEY,
  email      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
