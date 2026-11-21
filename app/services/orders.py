"""Order creation, payment recording and status workflow.

Design notes
- Stock is reserved (deducted) inside the same transaction that creates the order, so two
  shoppers can never buy the last unit; unpaid orders are auto-cancelled and the stock returned.
- Order items are snapshots (name/SKU/size/colour/price) independent of the live catalogue.
- Payment outcome is recorded atomically; a partial unique index makes a double charge impossible.
"""
import secrets
import sqlite3

from ..db import transaction
from ..payments import get_provider, get_usable_provider
from ..util import clean, valid_email
from . import inventory, pricing

STATUSES = ["pending", "confirmed", "processing", "shipped", "delivered", "cancelled", "refunded"]
TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled", "refunded"},
    "processing": {"shipped", "cancelled", "refunded"},
    "shipped": {"delivered", "refunded"},
    "delivered": {"refunded"},
    "cancelled": set(),
    "refunded": set(),
}


class CheckoutError(Exception):
    pass


class StockError(CheckoutError):
    pass


class OrderStateError(Exception):
    pass


# ---- validation --------------------------------------------------------------------------
def validate_checkout(form, settings):
    """Returns (clean_data, errors{field: message})."""
    d, errors = {}, {}
    d["email"] = clean(form.get("email"), 254).lower()
    if not valid_email(d["email"]):
        errors["email"] = "Enter a valid email address."
    d["phone"] = clean(form.get("phone"), 30)
    if len(d["phone"].replace("+", "").replace(" ", "").replace("-", "")) < 6 or not all(
        c.isdigit() or c in "+ -()" for c in d["phone"]
    ):
        errors["phone"] = "Enter a valid phone number."
    d["ship_name"] = clean(form.get("ship_name"), 120)
    if len(d["ship_name"]) < 2:
        errors["ship_name"] = "Enter the recipient's full name."
    d["ship_line1"] = clean(form.get("ship_line1"), 160)
    if len(d["ship_line1"]) < 3:
        errors["ship_line1"] = "Enter a street address."
    d["ship_line2"] = clean(form.get("ship_line2"), 160)
    d["ship_city"] = clean(form.get("ship_city"), 100)
    if not d["ship_city"]:
        errors["ship_city"] = "Enter a city."
    d["ship_region"] = clean(form.get("ship_region"), 100)
    d["ship_postal"] = clean(form.get("ship_postal"), 20)
    d["ship_country"] = clean(form.get("ship_country"), 80)
    countries = settings.get("shipping_countries") or []
    if countries and d["ship_country"] not in countries:
        errors["ship_country"] = "We don't ship to that country."
    elif not d["ship_country"]:
        errors["ship_country"] = "Choose a country."
    d["customer_note"] = clean(form.get("customer_note"), 500)
    d["payment_method"] = clean(form.get("payment_method"), 40)
    pm = next((m for m in settings["payment_methods"] if m["code"] == d["payment_method"] and m["enabled"]), None)
    if pm is None:
        errors["payment_method"] = "Choose a payment method."
    try:
        d["shipping_method_id"] = int(form.get("shipping_method_id", ""))
    except (TypeError, ValueError):
        d["shipping_method_id"] = None
        errors["shipping_method_id"] = "Choose a delivery method."
    return d, errors


# ---- creation ----------------------------------------------------------------------------
def _new_number(db, prefix):
    while True:
        number = f"{prefix}-{secrets.token_hex(3).upper()}"
        if not db.execute("SELECT 1 FROM orders WHERE number=?", (number,)).fetchone():
            return number


def create_order(db, settings, cart_id, data, customer_id=None, idempotency_key=None):
    """Returns (order_row, created). Raises CheckoutError / StockError with a user-safe message."""
    if idempotency_key:
        existing = db.execute("SELECT * FROM orders WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing:
            return existing, False

    pm = next((m for m in settings["payment_methods"] if m["code"] == data["payment_method"] and m["enabled"]), None)
    provider = get_usable_provider(pm["provider"]) if pm else None
    if provider is None:
        raise CheckoutError("That payment method isn't available.")

    with transaction(db):
        if idempotency_key:  # re-check under the write lock (double-click / concurrent submit)
            existing = db.execute("SELECT * FROM orders WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                return existing, False

        cart = db.execute("SELECT * FROM carts WHERE id=?", (cart_id,)).fetchone()
        lines = pricing.cart_lines(db, cart_id)
        if not lines:
            raise CheckoutError("Your cart is empty.")
        for l in lines:
            if l["issue"]:
                raise StockError(f"“{l['name']}” is no longer available in the quantity you selected. Please review your cart.")

        shipping = db.execute(
            "SELECT * FROM shipping_methods WHERE id=? AND is_active=1", (data["shipping_method_id"],)
        ).fetchone()
        if shipping is None:
            raise CheckoutError("Please choose a delivery method.")
        q = pricing.quote(db, lines, shipping, cart["discount_code"], settings)
        if cart["discount_code"] and q["discount_error"]:
            raise CheckoutError(q["discount_error"])

        number = _new_number(db, settings.get("order_prefix") or "ORD")
        confirmed_now = not provider.requires_payment_step
        cur = db.execute(
            "INSERT INTO orders(number, customer_id, email, phone, status, payment_status, payment_method,"
            " payment_provider, currency, subtotal_cents, discount_cents, discount_code, shipping_cents,"
            " shipping_method, tax_cents, tax_inclusive, total_cents, ship_name, ship_line1, ship_line2,"
            " ship_city, ship_region, ship_postal, ship_country, customer_note, access_token, idempotency_key)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                number, customer_id, data["email"], data["phone"],
                "confirmed" if confirmed_now else "pending", "unpaid", pm["code"], provider.code,
                settings.get("currency", "EUR"), q["subtotal"], q["discount"], q["discount_code"],
                q["shipping"], shipping["name"], q["tax"], int(q["tax_inclusive"]), q["total"],
                data["ship_name"], data["ship_line1"], data["ship_line2"], data["ship_city"],
                data["ship_region"], data["ship_postal"], data["ship_country"], data["customer_note"],
                secrets.token_urlsafe(24), idempotency_key,
            ),
        )
        order_id = cur.lastrowid

        for l in lines:
            db.execute(
                "INSERT INTO order_items(order_id, product_id, variant_id, product_name, sku, size, color, image,"
                " unit_price_cents, compare_price_cents, quantity, line_total_cents) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (order_id, l["product_id"], l["variant_id"], l["name"], l["sku"], l["size"], l["color"],
                 l["image"] or "", l["unit_cents"], l["price_cents"], l["quantity"], l["line_cents"]),
            )
            try:
                inventory.adjust(db, l["variant_id"], -l["quantity"], "order", f"Order {number}", order_id=order_id)
            except inventory.InsufficientStock:
                raise StockError(f"“{l['name']}” just sold out. Please review your cart.")

        if q["discount_code"]:
            cur = db.execute(
                "UPDATE discounts SET used_count = used_count + 1 WHERE code=? AND (max_uses IS NULL OR used_count < max_uses)",
                (q["discount_code"],),
            )
            if cur.rowcount != 1:
                raise CheckoutError("That discount code has just reached its usage limit.")

        db.execute(
            "INSERT INTO order_status_history(order_id, from_status, to_status, note) VALUES(?,?,?,?)",
            (order_id, None, "pending", "Order placed"),
        )
        if confirmed_now:
            db.execute(
                "INSERT INTO payments(order_id, provider, provider_ref, method, amount_cents, currency, status, is_simulated)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (order_id, provider.code, f"{provider.code.upper()}-{number}", pm["code"], q["total"],
                 settings.get("currency", "EUR"), "pending", int(provider.is_simulated)),
            )
            db.execute(
                "INSERT INTO order_status_history(order_id, from_status, to_status, note) VALUES(?,?,?,?)",
                (order_id, "pending", "confirmed", f"{pm['label']} — payment due on delivery"),
            )

        db.execute("DELETE FROM cart_items WHERE cart_id=?", (cart_id,))
        db.execute("UPDATE carts SET discount_code='' WHERE id=?", (cart_id,))
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    return order, True


# ---- payment -----------------------------------------------------------------------------
def pay_order(db, order_id, payload):
    """Run the order's payment provider and record the outcome atomically. Returns PaymentResult."""
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if order is None or order["status"] != "pending" or order["payment_status"] == "paid":
        raise OrderStateError("This order isn't awaiting payment.")
    provider = get_usable_provider(order["payment_provider"])
    if provider is None or not provider.requires_payment_step:
        raise OrderStateError("This order has no online payment step.")

    result = provider.process(order, payload)  # outside the DB lock (real providers do network I/O)

    try:
        with transaction(db):
            fresh = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if fresh["status"] != "pending" or fresh["payment_status"] == "paid":
                raise OrderStateError("This order isn't awaiting payment.")
            db.execute(
                "INSERT INTO payments(order_id, provider, provider_ref, method, amount_cents, currency, status,"
                " is_simulated, failure_reason) VALUES(?,?,?,?,?,?,?,?,?)",
                (order_id, provider.code, result.provider_ref, fresh["payment_method"], fresh["total_cents"],
                 fresh["currency"], "succeeded" if result.success else "failed", int(provider.is_simulated),
                 result.failure_reason),
            )
            if result.success:
                db.execute("UPDATE orders SET payment_status='paid', updated_at=datetime('now') WHERE id=?", (order_id,))
                _apply_status(db, fresh, "confirmed", note="Payment received" + (" (simulated)" if provider.is_simulated else ""))
            else:
                db.execute("UPDATE orders SET payment_status='failed', updated_at=datetime('now') WHERE id=?", (order_id,))
    except sqlite3.IntegrityError:
        raise OrderStateError("This order has already been paid.")
    return result


# ---- status workflow ---------------------------------------------------------------------
def _release_stock(db, order, user_id=None):
    if order["stock_released"]:
        return
    for it in db.execute("SELECT * FROM order_items WHERE order_id=? AND variant_id IS NOT NULL", (order["id"],)):
        inventory.adjust(db, it["variant_id"], it["quantity"], "order_cancelled",
                         f"Order {order['number']} {order['status']}→released", user_id, order["id"])
    db.execute("UPDATE orders SET stock_released=1 WHERE id=?", (order["id"],))
    if order["discount_code"]:
        db.execute("UPDATE discounts SET used_count = MAX(used_count - 1, 0) WHERE code=?", (order["discount_code"],))


def _apply_status(db, order, new_status, user_id=None, note=""):
    old = order["status"]
    if new_status == "cancelled" or (new_status == "refunded" and old in ("confirmed", "processing")):
        _release_stock(db, order, user_id)
    if new_status in ("cancelled", "refunded") and order["payment_status"] == "paid":
        db.execute("UPDATE payments SET status='refunded' WHERE order_id=? AND status='succeeded'", (order["id"],))
        db.execute("UPDATE orders SET payment_status='refunded' WHERE id=?", (order["id"],))
    if new_status == "delivered" and order["payment_status"] == "unpaid" and order["payment_provider"] == "cod":
        db.execute("UPDATE payments SET status='succeeded' WHERE order_id=? AND status='pending'", (order["id"],))
        db.execute("UPDATE orders SET payment_status='paid' WHERE id=?", (order["id"],))
    db.execute("UPDATE orders SET status=?, updated_at=datetime('now') WHERE id=?", (new_status, order["id"]))
    db.execute(
        "INSERT INTO order_status_history(order_id, from_status, to_status, note, user_id) VALUES(?,?,?,?,?)",
        (order["id"], old, new_status, note, user_id),
    )


def change_status(db, order_id, new_status, user_id=None, note=""):
    if new_status not in STATUSES:
        raise OrderStateError("Unknown status.")
    with transaction(db):
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if order is None:
            raise OrderStateError("Order not found.")
        if new_status not in TRANSITIONS[order["status"]]:
            raise OrderStateError(f"An order can't move from “{order['status']}” to “{new_status}”.")
        provider = get_provider(order["payment_provider"])
        if (new_status == "confirmed" and order["payment_status"] != "paid"
                and provider is not None and provider.requires_payment_step):
            raise OrderStateError("This order hasn't been paid yet, so it can't be confirmed.")
        _apply_status(db, order, new_status, user_id, note)


def expire_stale_orders(db, minutes):
    """Cancel online-payment orders left unpaid too long and return their stock."""
    rows = db.execute(
        "SELECT id FROM orders WHERE status='pending' AND payment_status IN ('unpaid','failed') "
        "AND created_at < datetime('now', ?)",
        (f"-{int(minutes)} minutes",),
    ).fetchall()
    for r in rows:
        try:
            change_status(db, r["id"], "cancelled", note="Auto-cancelled: payment not completed in time")
        except OrderStateError:
            pass
    return len(rows)


# ---- queries -----------------------------------------------------------------------------
def get_items(db, order_id):
    return db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY id", (order_id,)).fetchall()


def get_history(db, order_id):
    return db.execute(
        "SELECT h.*, u.name AS user_name FROM order_status_history h LEFT JOIN users u ON u.id=h.user_id "
        "WHERE h.order_id=? ORDER BY h.id",
        (order_id,),
    ).fetchall()


def get_payments(db, order_id):
    return db.execute("SELECT * FROM payments WHERE order_id=? ORDER BY id", (order_id,)).fetchall()
