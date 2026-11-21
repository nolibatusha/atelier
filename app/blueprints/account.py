"""Customer accounts: registration, login, profile, addresses, order history."""
from flask import (Blueprint, abort, flash, g, redirect, render_template, request, url_for)

from ..db import get_db, transaction
from ..security import (burn_password_check, customer_required, hash_password, is_staff, limiter, login_user,
                        logout_user, password_problem, rate_limit, verify_password)
from ..services import orders
from ..services import settings as settings_svc
from ..util import clean, safe_next, valid_email
from .cart import adopt_customer_cart

bp = Blueprint("account", __name__, url_prefix="/account")


def _after_login(db, user_row, nxt):
    login_user(user_row["id"])
    cust = db.execute("SELECT id FROM customers WHERE user_id=?", (user_row["id"],)).fetchone()
    g.customer = cust
    if cust:
        adopt_customer_cart(db, cust["id"])
    return redirect(nxt)


@bp.route("/register", methods=["GET", "POST"])
@rate_limit("register", 10, 3600)
def register():
    if g.user and g.customer:
        return redirect(url_for("account.dashboard"))
    form, errors = request.form, {}
    if request.method == "POST":
        email = clean(form.get("email"), 254).lower()
        first, last = clean(form.get("first_name"), 60), clean(form.get("last_name"), 60)
        phone = clean(form.get("phone"), 30)
        pw = form.get("password", "")
        if not valid_email(email):
            errors["email"] = "Enter a valid email address."
        if not first:
            errors["first_name"] = "Enter your first name."
        if (p := password_problem(pw)):
            errors["password"] = p
        elif pw != form.get("password2"):
            errors["password2"] = "Passwords don't match."
        db = get_db()
        if not errors and db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            errors["email"] = "An account with this email already exists. Try signing in."
        if not errors:
            with transaction(db):
                role = db.execute("SELECT id FROM roles WHERE name='customer'").fetchone()["id"]
                uid = db.execute(
                    "INSERT INTO users(email, password_hash, name, role_id) VALUES(?,?,?,?)",
                    (email, hash_password(pw), f"{first} {last}".strip(), role)).lastrowid
                db.execute("INSERT INTO customers(user_id, email, first_name, last_name, phone) VALUES(?,?,?,?,?)",
                           (uid, email, first, last, phone))
            user = db.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
            flash("Welcome! Your account has been created.", "success")
            return _after_login(db, user, safe_next(request.args.get("next"), url_for("account.dashboard")))
    return render_template("account/register.html", form=form, errors=errors), (422 if errors else 200)


@bp.route("/login", methods=["GET", "POST"])
@rate_limit("login-ip", 30, 600)
def login():
    if g.user and g.customer:
        return redirect(url_for("account.dashboard"))
    error = None
    nxt = safe_next(request.args.get("next") or request.form.get("next"), url_for("account.dashboard"))
    if request.method == "POST":
        email = clean(request.form.get("email"), 254).lower()
        pw = request.form.get("password", "")
        key = f"login-email:{email}"
        db = get_db()
        if limiter.blocked(key, 6, 900):
            error = "Too many failed attempts for this account. Please wait 15 minutes."
        else:
            user = db.execute("SELECT * FROM users WHERE email=? AND is_active=1", (email,)).fetchone()
            if user and verify_password(user["password_hash"], pw):
                limiter.reset(key)
                role = db.execute("SELECT permissions FROM roles WHERE id=?", (user["role_id"],)).fetchone()
                if role["permissions"]:  # staff sign in via /admin/login
                    return redirect(url_for("admin.login"))
                return _after_login(db, user, nxt)
            if not user:
                burn_password_check()
            limiter.hit(key, 900)
            error = "Incorrect email or password."
    return render_template("account/login.html", error=error, next=nxt), (401 if error else 200)


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("You've been signed out.", "info")
    return redirect(url_for("shop.home"))


@bp.route("/")
@customer_required
def dashboard():
    db = get_db()
    recent = db.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC LIMIT 3", (g.customer["id"],)).fetchall()
    n = db.execute("SELECT COUNT(*) FROM orders WHERE customer_id=?", (g.customer["id"],)).fetchone()[0]
    addr = db.execute("SELECT * FROM addresses WHERE customer_id=? ORDER BY is_default DESC, id LIMIT 1", (g.customer["id"],)).fetchone()
    return render_template("account/dashboard.html", recent=recent, order_count=n, address=addr)


@bp.route("/profile", methods=["GET", "POST"])
@customer_required
def profile():
    db, errors = get_db(), {}
    if request.method == "POST":
        first, last = clean(request.form.get("first_name"), 60), clean(request.form.get("last_name"), 60)
        phone = clean(request.form.get("phone"), 30)
        if not first:
            errors["first_name"] = "Enter your first name."
        else:
            with transaction(db):
                db.execute("UPDATE customers SET first_name=?, last_name=?, phone=? WHERE id=?",
                           (first, last, phone, g.customer["id"]))
                db.execute("UPDATE users SET name=? WHERE id=?", (f"{first} {last}".strip(), g.user["id"]))
            flash("Profile updated.", "success")
            return redirect(url_for("account.profile"))
    return render_template("account/profile.html", errors=errors)


@bp.route("/password", methods=["POST"])
@customer_required
@rate_limit("password", 10, 900)
def password():
    db = get_db()
    cur, new = request.form.get("current", ""), request.form.get("password", "")
    if not verify_password(g.user["password_hash"], cur):
        flash("Your current password is incorrect.", "error")
    elif (p := password_problem(new)):
        flash(p, "error")
    elif new != request.form.get("password2"):
        flash("New passwords don't match.", "error")
    else:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), g.user["id"]))
        flash("Password changed.", "success")
    return redirect(url_for("account.profile"))


# ---- addresses -------------------------------------------------------------------------------
def _address_from_form(form, countries):
    a = {k: clean(form.get(k), n) for k, n in [("label", 40), ("full_name", 120), ("line1", 160), ("line2", 160),
                                                 ("city", 100), ("region", 100), ("postal_code", 20),
                                                 ("country", 80), ("phone", 30)]}
    err = None
    if len(a["full_name"]) < 2 or len(a["line1"]) < 3 or not a["city"] or not a["country"]:
        err = "Please fill in name, street address, city and country."
    elif countries and a["country"] not in countries:
        err = "We don't ship to that country."
    return a, err


@bp.route("/addresses", methods=["GET", "POST"])
@customer_required
def addresses():
    db = get_db()
    countries = settings_svc.load(db).get("shipping_countries") or []
    if request.method == "POST":
        a, err = _address_from_form(request.form, countries)
        if err:
            flash(err, "error")
        else:
            with transaction(db):
                first = not db.execute("SELECT 1 FROM addresses WHERE customer_id=?", (g.customer["id"],)).fetchone()
                default = 1 if (first or request.form.get("is_default")) else 0
                if default:
                    db.execute("UPDATE addresses SET is_default=0 WHERE customer_id=?", (g.customer["id"],))
                db.execute(
                    "INSERT INTO addresses(customer_id, label, full_name, line1, line2, city, region, postal_code, country, phone, is_default)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (g.customer["id"], a["label"], a["full_name"], a["line1"], a["line2"], a["city"], a["region"],
                     a["postal_code"], a["country"], a["phone"], default))
            flash("Address saved.", "success")
        return redirect(url_for("account.addresses"))
    rows = db.execute("SELECT * FROM addresses WHERE customer_id=? ORDER BY is_default DESC, id", (g.customer["id"],)).fetchall()
    return render_template("account/addresses.html", addresses=rows, countries=countries)


def _own_address(db, address_id):
    row = db.execute("SELECT * FROM addresses WHERE id=? AND customer_id=?", (address_id, g.customer["id"])).fetchone()
    if row is None:
        abort(404)
    return row


@bp.route("/addresses/<int:address_id>/edit", methods=["POST"])
@customer_required
def address_edit(address_id):
    db = get_db()
    _own_address(db, address_id)
    countries = settings_svc.load(db).get("shipping_countries") or []
    a, err = _address_from_form(request.form, countries)
    if err:
        flash(err, "error")
    else:
        db.execute(
            "UPDATE addresses SET label=?, full_name=?, line1=?, line2=?, city=?, region=?, postal_code=?, country=?, phone=?"
            " WHERE id=? AND customer_id=?",
            (a["label"], a["full_name"], a["line1"], a["line2"], a["city"], a["region"], a["postal_code"], a["country"],
             a["phone"], address_id, g.customer["id"]))
        flash("Address updated.", "success")
    return redirect(url_for("account.addresses"))


@bp.route("/addresses/<int:address_id>/default", methods=["POST"])
@customer_required
def address_default(address_id):
    db = get_db()
    _own_address(db, address_id)
    with transaction(db):
        db.execute("UPDATE addresses SET is_default=0 WHERE customer_id=?", (g.customer["id"],))
        db.execute("UPDATE addresses SET is_default=1 WHERE id=?", (address_id,))
    return redirect(url_for("account.addresses"))


@bp.route("/addresses/<int:address_id>/delete", methods=["POST"])
@customer_required
def address_delete(address_id):
    db = get_db()
    _own_address(db, address_id)
    db.execute("DELETE FROM addresses WHERE id=? AND customer_id=?", (address_id, g.customer["id"]))
    flash("Address removed.", "info")
    return redirect(url_for("account.addresses"))


# ---- orders ----------------------------------------------------------------------------------
@bp.route("/orders")
@customer_required
def order_list():
    rows = get_db().execute("SELECT o.*, (SELECT COALESCE(SUM(quantity),0) FROM order_items WHERE order_id=o.id) AS n_items "
                            "FROM orders o WHERE customer_id=? ORDER BY id DESC", (g.customer["id"],)).fetchall()
    return render_template("account/orders.html", orders=rows)


@bp.route("/orders/<number>")
@customer_required
def order_detail(number):
    db = get_db()
    # Ownership enforced in the query itself: other customers' orders simply don't exist for you.
    order = db.execute("SELECT * FROM orders WHERE number=? AND customer_id=?", (number, g.customer["id"])).fetchone()
    if order is None:
        abort(404)
    return render_template("shop/order.html", order=order, items=orders.get_items(db, order["id"]),
                           history=orders.get_history(db, order["id"]), payments=orders.get_payments(db, order["id"]),
                           placed=False, back_url=url_for("account.order_list"))
