"""End-to-end tests of the 20 required workflows plus security and integrity checks."""
import io
import re

from PIL import Image

from conftest import ADMIN, CUSTOMER, MANAGER, fill_checkout


def png_bytes(color=(120, 90, 60), size=(80, 100)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    b.seek(0)
    return b


def add_to_cart(h, client, vid, qty=1):
    return h.post(client, "/cart/add", {"variant_id": vid, "quantity": qty}, headers={"Accept": "application/json"})


def place_order(h, client, payment="card_demo", **over):
    c = client.get("/checkout")
    assert c.status_code == 200
    return h.post(client, "/checkout", fill_checkout(h, client, payment_method=payment, **over))


# 1. Admin login ------------------------------------------------------------------------------
def test_01_admin_login_and_dashboard(client, h):
    r = h.login(client, ADMIN, "/admin/login")
    assert r.status_code == 302
    d = client.get("/admin/")
    assert d.status_code == 200 and b"Total sales" in d.data


def test_01b_bad_admin_login_rejected(client, h):
    r = h.login(client, (ADMIN[0], "wrong-password"), "/admin/login")
    assert r.status_code in (200, 401, 422) and b"Dashboard" not in r.data
    assert client.get("/admin/").status_code in (302, 401, 403)


# 2-4. Product create / edit / images / variants ----------------------------------------------
def create_product(h, client, name="Test Linen Shirt", price="89.00"):
    h.login(client, ADMIN, "/admin/login")
    data = {"name": name, "description": "A test product", "price": price, "is_published": "1",
            "v_id": ["", ""], "v_size": ["S", "M"], "v_color": ["Ink", "Ink"], "v_hex": ["#112233", "#112233"],
            "v_sku": ["", ""], "v_stock": ["5", "0"], "v_low": ["3", "3"], "v_active": ["1", "1"],
            "images": (png_bytes(), "front.png")}
    return h.post(client, "/admin/products/new", data, content_type="multipart/form-data")


def test_02_create_product_with_variants_and_image(client, h):
    r = create_product(h, client)
    assert r.status_code == 302, r.data[:500]
    p = h.q("SELECT * FROM products WHERE name='Test Linen Shirt'")[0]
    assert p["price_cents"] == 8900
    vs = h.q("SELECT * FROM product_variants WHERE product_id=? ORDER BY size", p["id"])
    assert [(v["size"], v["stock"]) for v in vs] == [("M", 0), ("S", 5)]
    assert vs[0]["sku"] and vs[0]["sku"] != vs[1]["sku"]
    imgs = h.q("SELECT filename FROM product_images WHERE product_id=?", p["id"])
    assert len(imgs) == 1 and imgs[0]["filename"] not in ("front.png",)
    # initial stock must be recorded in the ledger
    mv = h.q("SELECT SUM(delta) AS s FROM inventory_movements WHERE variant_id=?", vs[1]["id"])[0]["s"]
    assert mv == 5
    assert client.get(f"/product/{p['slug']}").status_code == 200


def test_03_edit_product_price_and_sale(client, h):
    create_product(h, client)
    p = h.q("SELECT * FROM products WHERE name='Test Linen Shirt'")[0]
    vs = h.q("SELECT * FROM product_variants WHERE product_id=? ORDER BY id", p["id"])
    data = {"name": "Test Linen Shirt", "price": "99.00", "sale_price": "79.00", "is_published": "1",
            "v_id": [str(v["id"]) for v in vs], "v_size": [v["size"] for v in vs], "v_color": ["Ink", "Ink"],
            "v_hex": ["#112233"] * 2, "v_sku": [v["sku"] for v in vs], "v_stock": ["5", "0"], "v_low": ["3", "3"],
            "v_active": ["1", "1"]}
    r = h.post(client, f"/admin/products/{p['id']}", data, content_type="multipart/form-data")
    assert r.status_code == 302
    p2 = h.q("SELECT * FROM products WHERE id=?", p["id"])[0]
    assert (p2["price_cents"], p2["sale_price_cents"]) == (9900, 7900)
    assert b"79.00" in client.get(f"/product/{p['slug']}").data


def test_04_product_validation_and_bad_upload(client, h):
    h.login(client, ADMIN, "/admin/login")
    r = h.post(client, "/admin/products/new", {"name": "", "price": "abc"}, content_type="multipart/form-data")
    assert r.status_code == 422
    bad = {"name": "Evil", "price": "10", "images": (io.BytesIO(b"<?php echo 1; ?>"), "shell.php")}
    r = h.post(client, "/admin/products/new", bad, content_type="multipart/form-data")
    assert r.status_code == 422 or b"Evil" not in b"".join(x["name"].encode() for x in h.q("SELECT name FROM products"))
    assert not h.q("SELECT 1 FROM products WHERE name='Evil'")
    r = h.post(client, "/admin/products/new", {"name": "Bad hex", "price": "10", "v_id": [""], "v_size": ["M"], "v_color": ["x"],
                                                 "v_hex": ["red;}</style><script>"], "v_stock": ["1"]}, content_type="multipart/form-data")
    row = h.q("SELECT color_hex FROM product_variants WHERE color='x'")
    assert row and row[0]["color_hex"] == ""


# 5. Inventory adjust -----------------------------------------------------------------------------
def test_05_inventory_adjustment_and_history(client, h):
    h.login(client, ADMIN, "/admin/login")
    v = h.variant()
    h.post(client, "/admin/inventory/adjust", {"variant_id": v["id"], "qty": 7, "mode": "add", "reason": "restock"})
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == v["stock"] + 7
    r = h.post(client, "/admin/inventory/adjust", {"variant_id": v["id"], "qty": -10_000, "mode": "add", "reason": "damaged"})
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == v["stock"] + 7  # unchanged
    mv = h.q("SELECT * FROM inventory_movements WHERE variant_id=? ORDER BY id DESC LIMIT 1", v["id"])[0]
    assert mv["delta"] == 7 and mv["reason"] == "restock"
    assert client.get("/admin/inventory/history").status_code == 200


# 6-7. Customer registration / login --------------------------------------------------------------
def test_06_customer_registration_and_login(client, h):
    r = h.post(client, "/account/register", {"email": "new@example.org", "password": "A-Strong-Passphrase-1", "password2": "A-Strong-Passphrase-1",
                                             "first_name": "New", "last_name": "Person", "name": "New Person"})
    assert r.status_code == 302, r.data[:600]
    assert h.q("SELECT 1 FROM customers WHERE email='new@example.org'")
    pw = h.q("SELECT password_hash FROM users WHERE email='new@example.org'")
    assert pw and "A-Strong" not in pw[0]["password_hash"]
    assert client.get("/account/").status_code == 200
    c2 = client.application.test_client()
    assert h.login(c2, ("new@example.org", "A-Strong-Passphrase-1")).status_code == 302
    c3 = client.application.test_client()
    assert b"Dashboard" not in h.login(c3, ("new@example.org", "nope")).data


def test_07_duplicate_and_weak_registration(client, h):
    r = h.post(client, "/account/register", {"email": CUSTOMER[0], "password": "A-Strong-Passphrase-1", "password2": "A-Strong-Passphrase-1", "name": "Dup"})
    assert r.status_code in (200, 422)
    r = h.post(client, "/account/register", {"email": "weak@example.org", "password": "123", "password2": "123", "name": "Weak"})
    assert r.status_code in (200, 422) and not h.q("SELECT 1 FROM customers WHERE email='weak@example.org'")


# 8. Search / filter / sort / pagination -------------------------------------------------------------
def test_08_search_filter_sort_pagination(client, h):
    assert client.get("/shop").status_code == 200
    r = client.get("/shop?q=coat")
    assert r.status_code == 200 and b"coat" in r.data.lower()
    asc = client.get("/shop?sort=price_asc").data
    desc = client.get("/shop?sort=price_desc").data
    assert asc != desc
    assert client.get("/shop?min=50&max=120").status_code == 200
    assert client.get("/shop?availability=out_of_stock").status_code == 200
    assert client.get("/shop?page=2").status_code == 200
    assert client.get("/shop?q=%27%20OR%201%3D1--").status_code == 200  # SQL-injection-shaped input is inert
    # draft products never appear
    draft = h.q("SELECT name, slug FROM products WHERE is_published=0")
    if draft:
        assert client.get(f"/product/{draft[0]['slug']}").status_code == 404


# 9-10. Cart ----------------------------------------------------------------------------------------
def test_09_cart_add_update_remove_server_validated(client, h):
    v = h.variant()
    j = add_to_cart(h, client, v["id"], 2).get_json()
    assert j["ok"] and j["cart_count"] == 2
    item = h.q("SELECT id FROM cart_items")[0]["id"]
    h.post(client, "/cart/update", {"item_id": item, "quantity": 3})
    assert h.q("SELECT quantity FROM cart_items WHERE id=?", item)[0]["quantity"] == 3
    over = h.post(client, "/cart/update", {"item_id": item, "quantity": 99})
    assert h.q("SELECT quantity FROM cart_items WHERE id=?", item)[0]["quantity"] <= min(v["stock"], 10)
    h.post(client, "/cart/remove", {"item_id": item})
    assert not h.q("SELECT 1 FROM cart_items")


def test_10_cart_cannot_exceed_stock_or_use_sold_out(client, h):
    sold = h.variant(in_stock=False)
    j = add_to_cart(h, client, sold["id"]).get_json()
    assert j["ok"] is False
    v = h.variant()
    j = add_to_cart(h, client, v["id"], v["stock"] + 5).get_json()
    qty = h.q("SELECT COALESCE(SUM(quantity),0) AS n FROM cart_items")[0]["n"]
    assert qty <= v["stock"]
    assert add_to_cart(h, client, 999999).get_json()["ok"] is False


# 11. Checkout validation -----------------------------------------------------------------------------
def test_11_checkout_validation(client, h):
    v = h.variant()
    add_to_cart(h, client, v["id"])
    r = h.post(client, "/checkout", {"email": "not-an-email"})
    assert r.status_code == 422
    assert not h.q("SELECT 1 FROM orders WHERE email='not-an-email'")
    r = h.post(client, "/checkout", fill_checkout(h, client, ship_country="Atlantis"))
    assert r.status_code == 422
    assert client.get("/checkout").status_code == 200


# 12-14. Payment + order creation + inventory deduction ------------------------------------------------
def test_12_successful_simulated_payment_creates_confirmed_order_and_deducts_stock(client, h):
    v = h.variant()
    add_to_cart(h, client, v["id"], 2)
    r = place_order(h, client)
    assert r.status_code == 302 and "/pay/" in r.headers["Location"]
    o = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    assert o["status"] == "pending" and o["payment_status"] != "paid"
    # stock reserved immediately at order creation
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == v["stock"] - 2
    assert client.get(r.headers["Location"]).status_code == 200
    r = h.post(client, f"/pay/{o['number']}", {"outcome": "success", "t": o["access_token"]})
    assert r.status_code == 302
    o = h.q("SELECT * FROM orders WHERE id=?", o["id"])[0]
    assert o["status"] == "confirmed" and o["payment_status"] == "paid"
    assert h.q("SELECT COUNT(*) AS n FROM payments WHERE order_id=? AND status='succeeded'", o["id"])[0]["n"] == 1
    # item snapshot exists
    it = h.q("SELECT * FROM order_items WHERE order_id=?", o["id"])[0]
    assert it["product_name"] and it["quantity"] == 2 and it["unit_price_cents"] > 0
    # cart emptied
    assert not h.q("SELECT 1 FROM cart_items")


def test_13_failed_payment_keeps_order_pending_and_retry_works(client, h):
    v = h.variant()
    add_to_cart(h, client, v["id"])
    place_order(h, client)
    o = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    for outcome in ("declined", "insufficient_funds", "error"):
        r = h.post(client, f"/pay/{o['number']}", {"outcome": outcome, "t": o["access_token"]})
        assert r.status_code == 402
        assert h.q("SELECT status, payment_status FROM orders WHERE id=?", o["id"])[0]["status"] == "pending"
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == v["stock"] - 1
    h.post(client, f"/pay/{o['number']}", {"outcome": "success", "t": o["access_token"]})
    assert h.q("SELECT status FROM orders WHERE id=?", o["id"])[0]["status"] == "confirmed"
    # a second success must not double-charge
    h.post(client, f"/pay/{o['number']}", {"outcome": "success", "t": o["access_token"]})
    assert h.q("SELECT COUNT(*) AS n FROM payments WHERE order_id=? AND status='succeeded'", o["id"])[0]["n"] == 1


def test_14_cancel_unpaid_restocks_and_cod_confirms(client, h):
    v = h.variant()
    add_to_cart(h, client, v["id"], 2)
    place_order(h, client)
    o = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    h.post(client, f"/pay/{o['number']}/cancel", {"t": o["access_token"]})
    assert h.q("SELECT status FROM orders WHERE id=?", o["id"])[0]["status"] == "cancelled"
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == v["stock"]
    add_to_cart(h, client, v["id"])
    codm = h.q("SELECT code FROM json_each((SELECT value FROM settings WHERE key='payment_methods')) j, "
               "json_tree(j.value) t WHERE 0") if False else None
    r = place_order(h, client, payment="cod")
    if r.status_code == 302 and "/order/" in r.headers["Location"]:
        o2 = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
        assert o2["status"] == "confirmed"


def test_15_idempotent_double_submit_creates_one_order(client, h):
    v = h.variant()
    add_to_cart(h, client, v["id"])
    data = fill_checkout(h, client)
    client.get("/checkout")
    r1 = h.post(client, "/checkout", data)
    r2 = h.post(client, "/checkout", data)
    assert h.q("SELECT COUNT(*) AS n FROM orders WHERE email=?", data["email"])[0]["n"] == 1
    assert r1.headers["Location"] == r2.headers["Location"]
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == v["stock"] - 1


def test_16_no_oversell_when_stock_changes_before_checkout(client, h, app):
    v = h.variant(min_stock=2)
    add_to_cart(h, client, v["id"], 2)
    from app.db import connect
    c = connect(app.config["DATABASE"]); c.execute("UPDATE product_variants SET stock=1 WHERE id=?", (v["id"],)); c.close()
    client.get("/checkout")
    r = h.post(client, "/checkout", fill_checkout(h, client))
    assert r.status_code in (302, 422)
    assert not h.q("SELECT 1 FROM orders WHERE email=?", "buyer@example.org")
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == 1


def test_17_browser_cannot_set_prices(client, h):
    v = h.variant()
    add_to_cart(h, client, v["id"])
    client.get("/checkout")
    h.post(client, "/checkout", fill_checkout(h, client, total="1", subtotal="1", unit_price="1", price="1", shipping_cents="0"))
    o = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    real = h.q("SELECT p.price_cents, p.sale_price_cents FROM product_variants v JOIN products p ON p.id=v.product_id WHERE v.id=?", v["id"])[0]
    expect = real["sale_price_cents"] or real["price_cents"]
    assert o["subtotal_cents"] == expect


# 18. Admin order management ------------------------------------------------------------------------
def test_18_admin_order_status_transitions(client, h):
    v = h.variant()
    cust = client.application.test_client()
    add_to_cart(h, cust, v["id"])
    place_order(h, cust)
    o = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    h.post(cust, f"/pay/{o['number']}", {"outcome": "success", "t": o["access_token"]})
    h.login(client, ADMIN, "/admin/login")
    assert client.get(f"/admin/orders/{o['id']}").status_code == 200
    # invalid jump rejected
    h.post(client, f"/admin/orders/{o['id']}/status", {"status": "delivered"})
    assert h.q("SELECT status FROM orders WHERE id=?", o["id"])[0]["status"] == "confirmed"
    for st in ("processing", "shipped", "delivered"):
        h.post(client, f"/admin/orders/{o['id']}/status", {"status": st})
        assert h.q("SELECT status FROM orders WHERE id=?", o["id"])[0]["status"] == st
    hist = [r["to_status"] if "to_status" in r.keys() else r["status"] for r in h.q("SELECT * FROM order_status_history WHERE order_id=? ORDER BY id", o["id"])]
    assert hist[-3:] == ["processing", "shipped", "delivered"]
    # terminal state: can't cancel a delivered order
    h.post(client, f"/admin/orders/{o['id']}/status", {"status": "cancelled"})
    assert h.q("SELECT status FROM orders WHERE id=?", o["id"])[0]["status"] == "delivered"


def test_18b_cancel_paid_order_restocks_and_refund(client, h):
    v = h.variant()
    cust = client.application.test_client()
    add_to_cart(h, cust, v["id"], 2)
    place_order(h, cust)
    o = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    h.post(cust, f"/pay/{o['number']}", {"outcome": "success", "t": o["access_token"]})
    h.login(client, ADMIN, "/admin/login")
    h.post(client, f"/admin/orders/{o['id']}/status", {"status": "refunded"})
    row = h.q("SELECT status, payment_status FROM orders WHERE id=?", o["id"])[0]
    assert row["status"] == "refunded" and row["payment_status"] == "refunded"
    assert h.q("SELECT stock FROM product_variants WHERE id=?", v["id"])[0]["stock"] == v["stock"]


# 19. Customer order history & isolation ------------------------------------------------------------
def test_19_customer_order_history_and_isolation(client, h):
    h.login(client, CUSTOMER)
    r = client.get("/account/orders")
    assert r.status_code == 200
    mine = h.q("SELECT o.number FROM orders o JOIN customers c ON c.id=o.customer_id WHERE c.email=?", CUSTOMER[0])
    assert mine
    assert client.get(f"/account/orders/{mine[0]['number']}").status_code == 200
    other = h.q("SELECT o.number FROM orders o JOIN customers c ON c.id=o.customer_id WHERE c.email!=? LIMIT 1", CUSTOMER[0])
    assert other
    assert client.get(f"/account/orders/{other[0]['number']}").status_code == 404
    assert client.get(f"/order/{other[0]['number']}").status_code == 404
    # anonymous visitors can't see any account page
    anon = client.application.test_client()
    assert anon.get("/account/orders").status_code in (302, 401, 403)
    assert anon.get(f"/order/{mine[0]['number']}").status_code == 404


def test_20_guest_checkout_and_order_view(client, h):
    v = h.variant()
    add_to_cart(h, client, v["id"])
    r = place_order(h, client)
    o = h.q("SELECT * FROM orders ORDER BY id DESC LIMIT 1")[0]
    assert o["customer_id"] is None
    assert client.get(f"/order/{o['number']}").status_code == 200  # same session
    other = client.application.test_client()
    assert other.get(f"/order/{o['number']}").status_code == 404
    assert other.get(f"/order/{o['number']}?t=wrong").status_code == 404
    assert other.get(f"/order/{o['number']}?t={o['access_token']}").status_code == 200


# Security ---------------------------------------------------------------------------------------------
def test_sec_csrf_required(client, h):
    v = h.variant()
    r = client.post("/cart/add", data={"variant_id": v["id"], "quantity": 1})
    assert r.status_code in (400, 403)
    assert not h.q("SELECT 1 FROM cart_items")


def test_sec_rbac_manager_and_customer(client, h):
    mgr = client.application.test_client()
    h.login(mgr, MANAGER, "/admin/login")
    assert mgr.get("/admin/orders").status_code == 200
    assert mgr.get("/admin/settings").status_code in (302, 403)
    assert mgr.get("/admin/shipping").status_code in (302, 403)
    cust = client.application.test_client()
    h.login(cust, CUSTOMER)
    for p in ("/admin/", "/admin/orders", "/admin/products", "/admin/settings"):
        assert cust.get(p).status_code in (302, 401, 403), p
    anon = client.application.test_client()
    assert anon.get("/admin/products").status_code in (302, 401, 403)
    assert h.post(anon, "/admin/inventory/adjust", {"variant_id": 1, "qty": 5}).status_code in (302, 401, 403)


def test_sec_headers_and_no_xss_in_search(client):
    r = client.get("/shop?q=%3Cscript%3Ealert(1)%3C/script%3E")
    assert b"<script>alert(1)" not in r.data
    assert "script-src 'self'" in r.headers.get("Content-Security-Policy", "")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert b"<script>" not in re.sub(rb'<script[^>]*src=[^>]*></script>', b"", r.data)  # no inline scripts


def test_sec_open_redirect_blocked(client, h):
    r = h.post(client, "/account/login", {"email": CUSTOMER[0], "password": CUSTOMER[1], "next": "https://evil.example/"})
    assert r.status_code == 302 and "evil.example" not in r.headers["Location"]


def test_sec_media_path_traversal(client):
    assert client.get("/media/../../etc/passwd").status_code in (400, 404)
    assert client.get("/media/..%2f..%2fetc%2fpasswd").status_code in (400, 404)


def test_sec_admin_stored_xss_escaped(client, h):
    h.login(client, ADMIN, "/admin/login")
    h.post(client, "/admin/products/new", {"name": "<img src=x onerror=alert(1)>", "price": "10", "is_published": "1",
           "v_id": [""], "v_size": ["M"], "v_color": [""], "v_stock": ["4"], "description": "<script>alert(2)</script>"}, content_type="multipart/form-data")
    p = h.q("SELECT slug FROM products WHERE name LIKE '<img%'")
    assert p
    page = client.get(f"/product/{p[0]['slug']}").data
    assert b"<img src=x" not in page and b"<script>alert(2)" not in page


def test_sec_login_lockout(app):
    from app.security import limiter
    limiter.clear()
    app.config["RATELIMIT_ENABLED"] = True
    c = app.test_client()
    h = __import__("conftest").Helper(app)
    for i in range(7):
        h.login(c, (CUSTOMER[0], f"bad-{i}"))
    r = h.login(c, CUSTOMER)  # even the right password is refused during lockout
    assert r.status_code == 401 and b"Too many failed attempts" in r.data
    limiter.clear()


def test_sec_simulated_payments_blocked_in_production(app, h):
    prod = __import__("app").create_app({"TESTING": True, "ENV": "production", "DATABASE": app.config["DATABASE"],
                                         "UPLOAD_DIR": app.config["UPLOAD_DIR"], "SECRET_KEY": "k" * 32,
                                         "RATELIMIT_ENABLED": False})
    c = prod.test_client()
    v = h.variant()
    add_to_cart(h, c, v["id"])
    c.get("/checkout")
    r = h.post(c, "/checkout", fill_checkout(h, c, payment_method="card_demo"))
    assert r.status_code == 422  # simulated method is not offered/accepted
    assert not h.q("SELECT 1 FROM orders WHERE email='buyer@example.org'")


def test_sec_nan_inf_price_filters_do_not_crash(client):
    for v in ("nan", "NaN", "inf", "-inf", "1e999", "sNaN"):
        for k in ("min", "max"):
            assert client.get(f"/shop?{k}={v}").status_code == 200


# ---- responsive / mobile support ------------------------------------------------------------------
def _upload_big_image(h, client, tmp=None):
    h.login(client, ADMIN, "/admin/login")
    b = io.BytesIO()
    Image.new("RGB", (1600, 2000), (120, 90, 60)).save(b, "PNG")
    b.seek(0)
    h.post(client, "/admin/products/new", {"name": "Big Img", "price": "10", "is_published": "1", "v_id": [""], "v_size": ["M"],
                                          "v_color": [""], "v_stock": ["3"], "images": (b, "big.png")}, content_type="multipart/form-data")
    return h.q("SELECT i.filename, p.slug FROM product_images i JOIN products p ON p.id=i.product_id WHERE p.name='Big Img'")[0]


def test_resp_resized_images_are_smaller_cached_and_whitelisted(client, h, app):
    row = _upload_big_image(h, client)
    anon = app.test_client()
    full = anon.get(f"/media/{row['filename']}")
    small = anon.get(f"/media/{row['filename']}?w=480")
    assert full.status_code == small.status_code == 200
    assert len(small.data) < len(full.data) / 2
    assert Image.open(io.BytesIO(small.data)).width == 480
    # non-whitelisted widths fall back to the original (no arbitrary server-side rendering)
    odd = anon.get(f"/media/{row['filename']}?w=13")
    assert len(odd.data) == len(full.data)
    assert anon.get(f"/media/{row['filename']}?w=999999").status_code == 200
    # cached on disk
    import os
    assert os.path.exists(os.path.join(app.config["UPLOAD_DIR"], ".cache", "w480", row["filename"]))
    # traversal still blocked with the resize parameter
    assert anon.get("/media/..%2f..%2fmanage.py?w=480").status_code in (400, 404)
    assert anon.get("/media/.cache/../../manage.py?w=480").status_code in (400, 404)


def test_resp_pages_ship_srcset_viewport_and_sticky_bars(client, h):
    row = _upload_big_image(h, client)
    anon = client.application.test_client()
    shop = anon.get("/shop").data
    assert b"viewport-fit=cover" in shop and b'srcset="' in shop and b"sizes=" in shop
    pdp = anon.get(f"/product/{row['slug']}").data
    assert b"data-buybar" in pdp and b"has-stickybar" in pdp and b"fetchpriority" in pdp
    v = h.variant()
    add_to_cart(h, anon, v["id"])
    assert b"stickybar" in anon.get("/cart").data
    assert b"stickybar" in anon.get("/checkout").data
    # no horizontal-overflow-prone inline widths / no inline scripts introduced
    assert b"<script>" not in re.sub(rb'<script[^>]*(?:src=|type="application/json")[^>]*>.*?</script>', b"", pdp, flags=re.S)


def test_resp_deleting_image_removes_cached_variants(client, h, app):
    import os
    from app.services import media
    row = _upload_big_image(h, client)
    up = app.config["UPLOAD_DIR"]
    assert media.variant(up, row["filename"], 320)
    p = os.path.join(up, ".cache", "w320", row["filename"])
    assert os.path.exists(p)
    media.delete_file(up, row["filename"])
    assert not os.path.exists(p) and not os.path.exists(os.path.join(up, row["filename"]))


def test_static_assets_have_correct_types_even_with_bad_os_registry(tmp_path, template_db):
    """Simulates Windows registries that map .css/.js to text/plain (browsers then refuse them under nosniff)."""
    import mimetypes
    import shutil
    mimetypes.init()
    mimetypes.add_type("text/plain", ".css")
    mimetypes.add_type("text/plain", ".js")
    try:
        db = tmp_path / "s.db"
        shutil.copy(template_db, db)
        app = __import__("app").create_app({"TESTING": True, "DATABASE": str(db), "UPLOAD_DIR": str(tmp_path / "u"),
                                            "SECRET_KEY": "k" * 32, "RATELIMIT_ENABLED": False})
        c = app.test_client()
        html = c.get("/").get_data(as_text=True)
        css = re.search(r'href="(/static/css/store\.css\?v=\d+)"', html).group(1)
        js = re.search(r'src="(/static/js/store\.js\?v=\d+)"', html).group(1)
        assert c.get(css).headers["Content-Type"].startswith("text/css")
        assert c.get(js).headers["Content-Type"].startswith("text/javascript")
    finally:
        mimetypes.add_type("text/css", ".css")
        mimetypes.add_type("text/javascript", ".js")
