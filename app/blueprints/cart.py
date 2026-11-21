"""Cart, checkout, payment step and order confirmation."""
import hmac
import secrets

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)

from ..db import get_db
from ..payments import get_provider, get_usable_provider
from ..payments.simulated import OUTCOMES
from ..security import rate_limit
from ..services import cart as cartsvc
from ..services import orders, pricing
from ..services import settings as settings_svc
from ..util import clean, safe_next, to_int

bp = Blueprint("cart", __name__)
CART_COOKIE = "cart_token"


# ---- cart context --------------------------------------------------------------------------
def current_cart(create=False):
    cached = g.get("_cart", False)
    if cached is not False and (cached is not None or not create):
        return cached
    db = get_db()
    cart = cartsvc.find_by_token(db, request.cookies.get(CART_COOKIE))
    if cart is None and create:
        customer = g.get("customer")
        cart = cartsvc.create(db, customer["id"] if customer else None)
        g.new_cart_token = cart["token"]
    g._cart = cart
    return cart


def current_cart_count():
    cart = current_cart()
    return cartsvc.count(get_db(), cart["id"]) if cart else 0


@bp.after_app_request
def _set_cart_cookie(resp):
    token = g.get("new_cart_token")
    if token:
        resp.set_cookie(CART_COOKIE, token, max_age=60 * 60 * 24 * 30, httponly=True, samesite="Lax",
                        secure=current_app.config["SESSION_COOKIE_SECURE"])
    return resp


def adopt_customer_cart(db, customer_id):
    """After login: attach/merge the guest cart with any cart the customer already had."""
    guest = current_cart()
    others = db.execute("SELECT * FROM carts WHERE customer_id=? ORDER BY updated_at DESC", (customer_id,)).fetchall()
    others = [c for c in others if not guest or c["id"] != guest["id"]]
    if guest:
        for c in others:
            cartsvc.merge(db, guest["id"], c["id"])
        db.execute("UPDATE carts SET customer_id=? WHERE id=?", (customer_id, guest["id"]))
    elif others:
        keep = others[0]
        for c in others[1:]:
            cartsvc.merge(db, keep["id"], c["id"])
        g.new_cart_token = keep["token"]
        g._cart = keep


# ---- helpers -------------------------------------------------------------------------------
def _json_or_redirect(ok, message, nxt, status=200, **extra):
    if request.headers.get("Accept", "").startswith("application/json"):
        cart = current_cart()
        count = cartsvc.count(get_db(), cart["id"]) if cart else 0
        return jsonify(ok=ok, message=message, cart_count=count, **extra), (status if ok else 400)
    flash(message, "success" if ok else "error")
    return redirect(nxt)


def _cart_view(db, shipping_id=None):
    cart = current_cart()
    s = settings_svc.current()
    if not cart:
        return None, None, s
    lines = pricing.cart_lines(db, cart["id"])
    method = pricing.pick_shipping(db, shipping_id or cart["shipping_method_id"])
    return cart, pricing.quote(db, lines, method, cart["discount_code"], s), s


def _variants_for_lines(db, lines):
    out = {}
    for pid in {l["product_id"] for l in lines}:
        out[pid] = db.execute(
            "SELECT id, size, color, stock FROM product_variants WHERE product_id=? AND is_active=1 ORDER BY color, id", (pid,)
        ).fetchall()
    return out


# ---- cart pages / actions ------------------------------------------------------------------
@bp.route("/cart")
def view():
    db = get_db()
    cart, q, s = _cart_view(db)
    methods = pricing.active_shipping_methods(db)
    lines = q["lines"] if q else []
    return render_template("shop/cart.html", q=q, methods=methods, variants=_variants_for_lines(db, lines),
                           cart=cart, discount_input=(cart["discount_code"] if cart else ""))


@bp.route("/cart/add", methods=["POST"])
@rate_limit("cart-add", 120, 600)
def add():
    db = get_db()
    variant_id = to_int(request.form.get("variant_id"))
    qty = to_int(request.form.get("quantity"), 1, 1, 99)
    if not variant_id:
        return _json_or_redirect(False, "Please choose a size and colour.", request.referrer or url_for("shop.shop"))
    nxt = safe_next(request.form.get("next"), url_for("cart.view"))
    cart = current_cart(create=True)
    try:
        cartsvc.add_item(db, cart["id"], variant_id, qty, current_app.config["MAX_LINE_QTY"])
    except cartsvc.CartError as e:
        return _json_or_redirect(False, str(e), request.referrer or url_for("shop.shop"))
    if request.form.get("buy_now") and not request.headers.get("Accept", "").startswith("application/json"):
        return redirect(url_for("cart.checkout"))
    return _json_or_redirect(True, "Added to your bag.", nxt, cart_url=url_for("cart.view"))


def _cart_action(fn):
    db = get_db()
    cart = current_cart()
    nxt = safe_next(request.form.get("next"), url_for("cart.view"))
    if not cart:
        return redirect(nxt)
    try:
        fn(db, cart)
    except cartsvc.CartError as e:
        flash(str(e), "error")
    return redirect(nxt)


@bp.route("/cart/update", methods=["POST"])
def update():
    return _cart_action(lambda db, c: cartsvc.set_quantity(
        db, c["id"], to_int(request.form.get("item_id"), 0), to_int(request.form.get("quantity"), 1, 0, 99),
        current_app.config["MAX_LINE_QTY"]))


@bp.route("/cart/remove", methods=["POST"])
def remove():
    return _cart_action(lambda db, c: cartsvc.remove_item(db, c["id"], to_int(request.form.get("item_id"), 0)))


@bp.route("/cart/variant", methods=["POST"])
def change_variant():
    return _cart_action(lambda db, c: cartsvc.change_variant(
        db, c["id"], to_int(request.form.get("item_id"), 0), to_int(request.form.get("variant_id"), 0),
        current_app.config["MAX_LINE_QTY"]))


@bp.route("/cart/fix", methods=["POST"])
def fix():
    def go(db, c):
        n = cartsvc.fix_to_availability(db, c["id"])
        flash("Your bag was updated to match current availability." if n else "Nothing needed changing.", "info")
    return _cart_action(go)


@bp.route("/cart/discount", methods=["POST"])
@rate_limit("discount", 30, 600)
def discount():
    db = get_db()
    cart = current_cart(create=True)
    code = clean(request.form.get("code"), 40)
    nxt = safe_next(request.form.get("next"), url_for("cart.view"))
    if request.form.get("remove") or not code:
        db.execute("UPDATE carts SET discount_code='' WHERE id=?", (cart["id"],))
        return redirect(nxt)
    _, q, _s = _cart_view(db)
    sub = q["subtotal"] if q else 0
    row, err = pricing.validate_discount(db, code, sub)
    if err and "minimum" not in err:
        flash(err, "error")
    else:
        db.execute("UPDATE carts SET discount_code=? WHERE id=?", (code, cart["id"]))
        flash(err if err else f"Code {row['code']} applied.", "error" if err else "success")
    return redirect(nxt)


@bp.route("/cart/shipping", methods=["POST"])
def shipping():
    db = get_db()
    cart = current_cart(create=True)
    mid = to_int(request.form.get("shipping_method_id"))
    if mid and db.execute("SELECT 1 FROM shipping_methods WHERE id=? AND is_active=1", (mid,)).fetchone():
        db.execute("UPDATE carts SET shipping_method_id=? WHERE id=?", (mid, cart["id"]))
    return redirect(safe_next(request.form.get("next"), url_for("cart.view")))


# ---- checkout ------------------------------------------------------------------------------
def _prefill():
    c, u = g.get("customer"), g.get("user")
    data = {"email": u["email"] if u else "", "phone": c["phone"] if c else "",
            "ship_name": f"{c['first_name']} {c['last_name']}".strip() if c else "", "payment_method": ""}
    return data


def _render_checkout(db, cart, form, errors, status=200):
    s = settings_svc.current()
    lines = pricing.cart_lines(db, cart["id"])
    methods = pricing.active_shipping_methods(db)
    selected = pricing.pick_shipping(db, to_int(form.get("shipping_method_id")) or cart["shipping_method_id"])
    quotes = {m["id"]: pricing.quote(db, lines, m, cart["discount_code"], s) for m in methods}
    addresses = []
    if g.get("customer"):
        addresses = db.execute("SELECT * FROM addresses WHERE customer_id=? ORDER BY is_default DESC, id", (g.customer["id"],)).fetchall()
        if not form.get("ship_line1") and addresses:
            a = addresses[0]
            form = dict(form, ship_name=a["full_name"], ship_line1=a["line1"], ship_line2=a["line2"], ship_city=a["city"],
                        ship_region=a["region"], ship_postal=a["postal_code"], ship_country=a["country"],
                        phone=form.get("phone") or a["phone"])
    methods_enabled = [m for m in s["payment_methods"] if m["enabled"] and get_usable_provider(m["provider"])]
    if "checkout_key" not in session:
        session["checkout_key"] = secrets.token_urlsafe(18)
    return render_template(
        "shop/checkout.html", q=quotes[selected["id"]] if selected else pricing.quote(db, lines, None, cart["discount_code"], s),
        quotes=quotes, methods=methods, selected=selected, form=form, errors=errors, addresses=addresses,
        payment_methods=methods_enabled, countries=s.get("shipping_countries") or [],
        checkout_key=session["checkout_key"], discount_input=cart["discount_code"]), status


@bp.route("/checkout", methods=["GET", "POST"])
@rate_limit("checkout", 40, 600)
def checkout():
    db = get_db()
    s = settings_svc.current()
    orders.expire_stale_orders(db, s.get("pending_order_expiry_minutes", 120))
    cart = current_cart()
    if cart is None or cartsvc.count(db, cart["id"]) == 0:
        # A double-submit may land here after the first request already created the order.
        key = session.get("last_checkout_key")
        done = db.execute("SELECT * FROM orders WHERE idempotency_key=?", (key,)).fetchone() if key else None
        if done and request.method == "POST":
            return redirect(_after_order_url(done))
        flash("Your bag is empty.", "info")
        return redirect(url_for("cart.view"))

    if request.method == "GET":
        return _render_checkout(db, cart, _prefill(), {})[0]

    form = request.form
    data, errors = orders.validate_checkout(form, s)
    if errors:
        return _render_checkout(db, cart, form, errors, 422)
    key = session.get("checkout_key")
    if not key:
        key = session["checkout_key"] = secrets.token_urlsafe(18)
    try:
        order, created = orders.create_order(db, s, cart["id"], data, g.customer["id"] if g.get("customer") else None, key)
    except orders.StockError as e:
        flash(str(e), "error")
        return redirect(url_for("cart.view"))
    except orders.CheckoutError as e:
        return _render_checkout(db, cart, form, {"_form": str(e)}, 422)

    if created:
        guest = session.get("guest_orders", [])
        session["guest_orders"] = (guest + [order["number"]])[-20:]
        if g.get("customer") and form.get("save_address"):
            exists = db.execute(
                "SELECT 1 FROM addresses WHERE customer_id=? AND line1=? AND city=? AND country=?",
                (g.customer["id"], data["ship_line1"], data["ship_city"], data["ship_country"])).fetchone()
            if not exists:
                first = not db.execute("SELECT 1 FROM addresses WHERE customer_id=?", (g.customer["id"],)).fetchone()
                db.execute(
                    "INSERT INTO addresses(customer_id, label, full_name, line1, line2, city, region, postal_code, country, phone, is_default)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (g.customer["id"], "Saved at checkout", data["ship_name"], data["ship_line1"], data["ship_line2"],
                     data["ship_city"], data["ship_region"], data["ship_postal"], data["ship_country"], data["phone"], int(first)))
    session["last_checkout_key"] = session.pop("checkout_key", key)
    return redirect(_after_order_url(order))


def _after_order_url(order):
    provider = get_usable_provider(order["payment_provider"])
    if order["status"] == "pending" and provider and provider.requires_payment_step and order["payment_status"] != "paid":
        return url_for("cart.pay", number=order["number"])
    return url_for("cart.order_view", number=order["number"], placed=1)


# ---- order access / payment step ------------------------------------------------------------
def accessible_order(number):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE number=?", (number,)).fetchone()
    if order is None:
        abort(404)
    ok = bool(g.get("customer") and order["customer_id"] == g.customer["id"])
    token = request.args.get("t") or request.form.get("t") or ""
    if token and hmac.compare_digest(token.encode(), order["access_token"].encode()):
        ok = True
    if number in session.get("guest_orders", []):
        ok = True
    if not ok:
        abort(404)  # 404 (not 403) so order numbers can't be probed
    return order


@bp.route("/pay/<number>", methods=["GET", "POST"])
@rate_limit("pay", 40, 600)
def pay(number):
    db = get_db()
    order = accessible_order(number)
    provider = get_usable_provider(order["payment_provider"])
    if not (order["status"] == "pending" and provider and provider.requires_payment_step and order["payment_status"] != "paid"):
        return redirect(url_for("cart.order_view", number=number))
    error = None
    if request.method == "POST":
        outcome = request.form.get("outcome", "")
        if outcome not in OUTCOMES:
            abort(400)
        try:
            result = orders.pay_order(db, order["id"], {"outcome": outcome})
        except orders.OrderStateError as e:
            flash(str(e), "error")
            return redirect(url_for("cart.order_view", number=number))
        if result.success:
            flash("Payment received. Thank you for your order!", "success")
            return redirect(url_for("cart.order_view", number=number, placed=1))
        error = result.failure_reason or "The payment could not be completed."
        order = db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
    s = settings_svc.current()
    return render_template("shop/pay.html", order=order, items=orders.get_items(db, order["id"]), error=error,
                           outcomes=OUTCOMES, expiry=s.get("pending_order_expiry_minutes", 120),
                           token=order["access_token"]), (402 if error else 200)


@bp.route("/pay/<number>/cancel", methods=["POST"])
def cancel_unpaid(number):
    db = get_db()
    order = accessible_order(number)
    if order["status"] == "pending" and order["payment_status"] != "paid":
        try:
            orders.change_status(db, order["id"], "cancelled", note="Cancelled by customer before payment")
            flash("Your order was cancelled and the items were released.", "info")
        except orders.OrderStateError as e:
            flash(str(e), "error")
    return redirect(url_for("cart.order_view", number=number))


@bp.route("/order/<number>")
def order_view(number):
    db = get_db()
    order = accessible_order(number)
    return render_template("shop/order.html", order=order, items=orders.get_items(db, order["id"]),
                           history=orders.get_history(db, order["id"]), payments=orders.get_payments(db, order["id"]),
                           placed=bool(request.args.get("placed")), back_url=None)
