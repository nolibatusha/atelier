# ATELIER demo store (becomes "Sare the Brand")

A working e-commerce platform: Flask 3 + SQLite (WAL, foreign keys) + Jinja2 + vanilla JS. The ATELIER brand, products and
prices are fictional demo data that live only in `seed/`. Branding, shipping, tax, payment methods and homepage content are
editable at runtime under **/admin → Store settings / Shipping / Homepage / Pages**.

## Setup
```
pip install -r requirements.txt
cp .env.example .env          # set SECRET_KEY for production
python manage.py seed         # demo data (add --no-images to skip placeholder art)
python manage.py run          # http://127.0.0.1:5000   admin: /admin
python -m pytest tests -q     # 29 tests
```
`python manage.py reset` wipes DB + uploads and re-seeds. `python manage.py createadmin` creates a real admin from
ADMIN_EMAIL / ADMIN_PASSWORD (use this instead of the demo seed for launch).

## Demo credentials (change before any deployment)
- Admin: admin@example.com / ChangeMe-Demo-2026!
- Manager (limited): manager@example.com / Manager-Demo-2026!
- Customer: customer@example.com / Customer-Demo-2026!

## Structure
`app/services` business logic (pricing, cart, orders, inventory, catalog, media, settings) · `app/blueprints` storefront ·
`app/admin` back office · `app/payments` pluggable providers (simulated, cod) · `seed/` demo content · `tests/`.

## Responsive / mobile
Mobile-first layout tested at 320–1920px (phones, tablets, laptops, large monitors, landscape phones) with no sideways scrolling.
Phone extras: sticky "Add to bag" bar on product pages, sticky checkout / place-order bars, swipeable product gallery,
full-height filter drawer, stacked order tables, 16px inputs (no iOS zoom), 44px tap targets, safe-area support for notched
phones. Images are served resized on demand (`/media/<file>?w=480`, widths whitelisted, cached under `uploads/.cache/`) with
`srcset`, so phones download small files. The admin console is responsive too (drawer menu, scrolling tables).

## Database
users, roles, customers, addresses · categories, collections, products, product_collections, product_images,
product_variants (per-variant stock) · inventory_movements (ledger) · carts, cart_items · orders, order_items (price/name
snapshots), order_status_history, payments · shipping_methods, discounts · settings (JSON), pages, newsletter_subscribers.
Money is integer cents. Stock is reserved atomically at order creation and returned on cancel/refund/expiry.

## Before launch
Replace demo content and images · set SECRET_KEY, COOKIE_SECURE=1, HTTPS · replace the simulated provider with a real one in
`app/payments/` and disable it · configure shipping zones, tax, currency · write real legal pages · add transactional email ·
use Redis-backed rate limiting if running several workers · consider PostgreSQL at scale · back up `instance/`.

## Known limitations
Placeholder generated images; in-process rate limiter; SQLite scale limits; no email sending or verification; guest orders are
not auto-linked to later accounts; unused uploaded files are not garbage-collected; times shown in UTC; system font stack.
