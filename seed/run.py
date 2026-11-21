"""Loads the fictional demo store into an empty database. Uses the real application services
(cart, pricing, orders, inventory) so demo data obeys exactly the same rules as live data."""
import json
import secrets
from datetime import datetime, timedelta, timezone

from app.db import transaction
from app.security import hash_password
from app.services import cart as cart_svc
from app.services import inventory, orders
from app.services import settings as settings_svc
from app.util import slugify, unique_slug

from . import demo_data as D

NOW = lambda: datetime.now(timezone.utc).replace(tzinfo=None)
FMT = "%Y-%m-%d %H:%M:%S"


def is_empty(db):
    return db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0 and \
        db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def _images(upload_dir, with_images):
    """Generate placeholder imagery; returns dict of filenames (empty strings when disabled)."""
    out = {"products": {}, "collections": {}, "promos": ["", ""], "hero": "", "brand": "", "insta": []}
    if not with_images:
        return out
    from . import make_images as mi

    for i, p in enumerate(D.PRODUCTS):
        slug = slugify(p["name"])
        out["products"][slug] = mi.product_images(upload_dir, slug, p["kind"], p["opts"], p["colors"][0][1], i)
    hero, _ = mi.render_garment("coat", {"belt": True}, "#b08d63", ("#e9e1d3", "#cdbfa8"), size=(1920, 1080), k=0.9,
                                offset=(880, 0), arch=(1000, 70, 1600, 1080, "#f3ece0"), seed=7)
    out["hero"] = mi.save(hero, upload_dir, "demo-hero.jpg", 84)
    cols = [("sweater", {"neck": "turtle"}, "#8a5a3c", ("#dcc6aa", "#b99c7a"), "#cfb391"),
            ("coat", {}, "#c8ab82", ("#e7e1d5", "#cfc6b4"), "#f1ece2"),
            ("shirt", {"collar": True}, "#f1efe9", ("#a9b3a4", "#7f8a7c"), "#b9c3b4"),
            ("dress", {"straps": True}, "#1f2a44", ("#d9cfc3", "#b3a592"), "#e6ddd0")]
    for i, (kind, opts, c, bg, arch) in enumerate(cols):
        im, _ = mi.render_garment(kind, opts, c, bg, arch=(150, 150, 850, 1250, arch), seed=40 + i)
        out["collections"][i] = mi.save(im, upload_dir, f"demo-collection-{i + 1}.jpg")
    for i, (kind, opts, c, bg, off) in enumerate([("dress", {"straps": False}, "#b4694a", ("#e6d3c0", "#cdb197"), (860, 10)),
                                                  ("bag", {}, "#a5703d", ("#c9ccb8", "#9ea48b"), (780, 90))]):
        im, _ = mi.render_garment(kind, opts, c, bg, size=(1400, 700), k=0.55 if kind == "dress" else 0.6, offset=off, seed=60 + i)
        out["promos"][i] = mi.save(im, upload_dir, f"demo-promo-{i + 1}.jpg")
    brand = mi.fabric_scene((1000, 1250), ["#e6dccb", "#d5c6ae", "#c6b496", "#b8a283"], seed=5)
    out["brand"] = mi.save(brand, upload_dir, "demo-brand.jpg")
    insta = [mi.fabric_scene((800, 800), pal, seed=s) for pal, s in
             [(["#d9d2c4", "#b9ad98", "#8f836f"], 11), (["#d6c1ae", "#b99677", "#8a6a4f"], 12)]]
    for i, (kind, opts, c, bg) in enumerate([("sweater", {"neck": "crew"}, "#3f5240", ("#e3ddd0", "#cbc2b0")),
                                             ("pants", {"wide": True}, "#3b3b3d", ("#ddd6c9", "#c2b8a5")),
                                             ("coat", {"belt": True}, "#cdb99a", ("#4a4540", "#2f2b28")),
                                             ("scarf", {}, "#9a9a98", ("#e8dfd2", "#cfc1ac"))]):
        im, _ = mi.render_garment(kind, opts, c, bg, size=(800, 800), k=0.62, offset=(90, 12), seed=80 + i)
        insta.append(im)
    order = [2, 0, 3, 4, 1, 5]
    out["insta"] = [mi.save(insta[j], upload_dir, f"demo-insta-{n + 1}.jpg", 82) for n, j in enumerate(order)]
    return out


def seed(db, upload_dir, admin_email, admin_password, manager_password, customer_password, with_images=True):
    s_ctx = {}
    imgs = _images(upload_dir, with_images)

    with transaction(db):
        # ---- settings ----
        cfg = dict(D.BRAND_SETTINGS)
        cfg["hero_image"] = imgs["hero"]
        cfg["brand_intro_image"] = imgs["brand"]
        cfg["instagram_images"] = imgs["insta"]
        cfg["promo_banners"] = [dict(p, image=imgs["promos"][i]) for i, p in enumerate(D.PROMOS)]
        settings_svc.save_many(db, cfg)

        # ---- staff users ----
        role = lambda n: db.execute("SELECT id FROM roles WHERE name=?", (n,)).fetchone()["id"]
        for email, name, r, pw in [(admin_email, "Store Admin", "admin", admin_password),
                                   ("manager@example.com", "Store Manager", "manager", manager_password)]:
            db.execute("INSERT INTO users(email, password_hash, name, role_id) VALUES(?,?,?,?)",
                       (email, hash_password(pw), name, role(r)))

        # ---- taxonomy ----
        cat_ids, col_ids = {}, {}
        for i, (name, desc) in enumerate(D.CATEGORIES):
            cat_ids[name] = db.execute("INSERT INTO categories(slug, name, description, sort_order) VALUES(?,?,?,?)",
                                       (unique_slug(db, "categories", name), name, desc, i)).lastrowid
        for i, (name, desc, featured) in enumerate(D.COLLECTIONS):
            img = imgs["collections"].get(i, "")
            col_ids[name] = db.execute(
                "INSERT INTO collections(slug, name, description, image, sort_order, is_featured) VALUES(?,?,?,?,?,?)",
                (unique_slug(db, "collections", name), name, desc, img, i, int(featured))).lastrowid

        # ---- shipping & discounts & pages ----
        for m in D.SHIPPING:
            db.execute("INSERT INTO shipping_methods(name, description, price_cents, free_over_cents, sort_order) VALUES(?,?,?,?,?)",
                       (m["name"], m["description"], round(m["price"] * 100),
                        None if m["free_over"] is None else round(m["free_over"] * 100), m["sort_order"]))
        for d in D.DISCOUNTS:
            db.execute("INSERT INTO discounts(code, kind, value, min_subtotal_cents, max_uses) VALUES(?,?,?,?,?)",
                       (d["code"], d["kind"], d["value"] if d["kind"] == "percent" else round(d["value"] * 100),
                        round(d["min_subtotal"] * 100), d.get("max_uses")))
        for slug, title, body, footer, sort in D.PAGES:
            db.execute("INSERT INTO pages(slug, title, body, show_in_footer, sort_order) VALUES(?,?,?,?,?)",
                       (slug, title, body, footer, sort))

        # ---- products, variants, stock ----
        for pi, p in enumerate(D.PRODUCTS):
            slug = unique_slug(db, "products", p["name"])
            pid = db.execute(
                "INSERT INTO products(slug, name, description, details, category_id, price_cents, sale_price_cents,"
                " is_featured, is_published, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (slug, p["name"], p["description"], p["details"], cat_ids[p["category"]], round(p["price"] * 100),
                 None if p["sale"] is None else round(p["sale"] * 100), int(p["featured"]), 0 if p.get("draft") else 1,
                 (NOW() - timedelta(days=60 - pi * 3)).strftime(FMT))).lastrowid
            for cname in p["collections"]:
                db.execute("INSERT INTO product_collections(product_id, collection_id) VALUES(?,?)", (pid, col_ids[cname]))
            for pos, fn in enumerate(imgs["products"].get(slugify(p["name"]), [])):
                db.execute("INSERT INTO product_images(product_id, filename, alt, position) VALUES(?,?,?,?)",
                           (pid, fn, f"{p['name']} — view {pos + 1}", pos))
            for ci, (cname, chex) in enumerate(p["colors"]):
                for si, size in enumerate(p["sizes"]):
                    sku = f"{slug.upper()[:10]}-{slugify(cname).upper()[:6]}-{slugify(size).upper()}"
                    raw = (pid * 7 + si * 5 + ci * 3) % 13
                    stock = 0 if p.get("sold_out") else (raw + 6 if raw else 0)
                    if not p.get("sold_out") and (pid + si + ci) % 11 == 0:
                        stock = 2  # a few low-stock variants for the demo
                    vid = db.execute(
                        "INSERT INTO product_variants(product_id, sku, size, color, color_hex, stock, low_stock_threshold)"
                        " VALUES(?,?,?,?,?,0,3)", (pid, sku, size, cname, chex)).lastrowid
                    if stock:
                        inventory.adjust(db, vid, stock, "initial", "Demo opening stock")

        # ---- customers ----
        cust_ids, cust_rows = [], []
        for first, last, email, phone, city, country in D.DEMO_CUSTOMERS:
            pw = customer_password if email == "customer@example.com" else secrets.token_urlsafe(18)
            uid = db.execute("INSERT INTO users(email, password_hash, name, role_id) VALUES(?,?,?,?)",
                             (email, hash_password(pw), f"{first} {last}", role("customer"))).lastrowid
            cid = db.execute("INSERT INTO customers(user_id, email, first_name, last_name, phone) VALUES(?,?,?,?,?)",
                             (uid, email, first, last, phone)).lastrowid
            db.execute("INSERT INTO addresses(customer_id, label, full_name, line1, city, postal_code, country, phone, is_default)"
                       " VALUES(?,?,?,?,?,?,?,?,1)",
                       (cid, "Home", f"{first} {last}", f"Rruga e Demos {10 + cid}", city, f"{10000 + cid * 7}", country, phone))
            cust_ids.append(cid)
            cust_rows.append((cid, email, f"{first} {last}", phone, city, country))

    # ---- demo orders (through the real order pipeline, then back-dated) ----
    cfg = settings_svc.load(db)
    ship = {m["name"]: m["id"] for m in db.execute("SELECT * FROM shipping_methods")}
    for n, (ci, items, days, pay_code, code, path) in enumerate(D.DEMO_ORDERS):
        cart = cart_svc.create(db)
        ok = True
        for name, color, size, qty in items:
            v = db.execute(
                "SELECT v.id, v.stock FROM product_variants v JOIN products p ON p.id=v.product_id WHERE p.name=? AND v.color=? AND v.size=?",
                (name, color, size)).fetchone()
            if v["stock"] < qty + 2:  # make sure the demo order can be placed
                inventory.adjust(db, v["id"], qty + 4, "restock", "Demo restock")
            try:
                cart_svc.add_item(db, cart["id"], v["id"], qty, 10)
            except cart_svc.CartError:
                ok = False
        if not ok:
            continue
        db.execute("UPDATE carts SET discount_code=? WHERE id=?", (code, cart["id"]))
        if ci is None:
            email, name, phone, city, country = f"guest{n}@example.com", "Guest Shopper", "+383 44 000 111", "Prishtinë", "Kosovo"
            cid = None
        else:
            cid, email, name, phone, city, country = cust_rows[ci]
        data = dict(email=email, phone=phone, ship_name=name, ship_line1=f"Rruga e Demos {20 + n}", ship_line2="",
                    ship_city=city, ship_region="", ship_postal="10000", ship_country=country, customer_note="",
                    payment_method=pay_code, shipping_method_id=ship["Standard delivery" if n % 4 else "Express delivery"])
        order, _ = orders.create_order(db, cfg, cart["id"], data, cid, None)
        if order["payment_provider"] == "simulated":
            outcome = "success" if not (n == len(D.DEMO_ORDERS) - 1) else "declined"
            orders.pay_order(db, order["id"], {"outcome": outcome})
        for st in path:
            orders.change_status(db, order["id"], st, note="Demo data")
        if path and path[-1] in ("shipped", "delivered"):
            db.execute("UPDATE orders SET carrier='DHL', tracking_number=? WHERE id=?", (f"JD01460000{n:05d}", order["id"]))
        _backdate(db, order["id"], NOW() - timedelta(days=days, hours=n % 7, minutes=n * 3) if days else NOW() - timedelta(minutes=12 + n))

    # a few newsletter subscribers
    for e in ("anna@example.com", "luan@example.com", "sara@example.com"):
        db.execute("INSERT OR IGNORE INTO newsletter_subscribers(email) VALUES(?)", (e,))


def _backdate(db, order_id, when):
    """Spread an order's timestamps out realistically after creation."""
    t0 = when
    db.execute("UPDATE orders SET created_at=?, updated_at=? WHERE id=?", (t0.strftime(FMT), (t0 + timedelta(hours=40)).strftime(FMT), order_id))
    for i, h in enumerate(db.execute("SELECT id FROM order_status_history WHERE order_id=? ORDER BY id", (order_id,)).fetchall()):
        db.execute("UPDATE order_status_history SET created_at=? WHERE id=?", ((t0 + timedelta(hours=i * 9, minutes=i)).strftime(FMT), h["id"]))
    db.execute("UPDATE payments SET created_at=? WHERE order_id=?", ((t0 + timedelta(minutes=2)).strftime(FMT), order_id))
    db.execute("UPDATE inventory_movements SET created_at=? WHERE order_id=?", (t0.strftime(FMT), order_id))
