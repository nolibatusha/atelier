"""Dashboard, orders, customers, newsletter."""
import csv
import io
from datetime import date, timedelta

from flask import Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..db import get_db, transaction
from ..security import staff_required
from ..services import orders as orders_svc
from ..services import settings as settings_svc
from ..util import clean, to_int
from . import bp

SALE_STATUSES = "('confirmed','processing','shipped','delivered')"


def _like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@bp.route("/")
@staff_required()
def dashboard():
    db = get_db()
    s = settings_svc.load(db)
    orders_svc.expire_stale_orders(db, s.get("pending_order_expiry_minutes", 120))
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    stats = {
        "sales": one(f"SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE status IN {SALE_STATUSES}"),
        "orders": one("SELECT COUNT(*) FROM orders"),
        "to_fulfil": one("SELECT COUNT(*) FROM orders WHERE status IN ('confirmed','processing')"),
        "customers": one("SELECT COUNT(*) FROM customers"),
        "products": one("SELECT COUNT(*) FROM products"),
        "published": one("SELECT COUNT(*) FROM products WHERE is_published=1"),
        "low_stock": one("SELECT COUNT(*) FROM product_variants WHERE is_active=1 AND stock <= low_stock_threshold"),
        "aov": one(f"SELECT COALESCE(AVG(total_cents),0) FROM orders WHERE status IN {SALE_STATUSES}"),
    }
    recent = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 8").fetchall()
    best = db.execute(
        f"SELECT oi.product_name, MAX(oi.image) AS image, SUM(oi.quantity) AS qty, SUM(oi.line_total_cents) AS revenue "
        f"FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status IN {SALE_STATUSES} "
        f"GROUP BY oi.product_name ORDER BY qty DESC, revenue DESC LIMIT 5").fetchall()

    today = date.today()
    start = today - timedelta(days=29)
    by_day = {r["d"]: r for r in db.execute(
        f"SELECT date(created_at) AS d, SUM(total_cents) AS cents, COUNT(*) AS n FROM orders "
        f"WHERE status IN {SALE_STATUSES} AND date(created_at) >= ? GROUP BY date(created_at)", (start.isoformat(),))}
    series = []
    for i in range(30):
        d = start + timedelta(days=i)
        r = by_day.get(d.isoformat())
        series.append({"date": d, "cents": r["cents"] if r else 0, "n": r["n"] if r else 0})
    peak = max([p["cents"] for p in series] + [1])
    for p in series:
        p["pct"] = round(p["cents"] * 100 / peak)
    totals30 = {"cents": sum(p["cents"] for p in series), "n": sum(p["n"] for p in series)}
    status_counts = db.execute("SELECT status, COUNT(*) AS n FROM orders GROUP BY status").fetchall()
    return render_template("admin/dashboard.html", stats=stats, recent=recent, best=best, series=series,
                           totals30=totals30, status_counts=status_counts)


# ---- orders -----------------------------------------------------------------------------------
@bp.route("/orders")
@staff_required("orders")
def orders():
    db = get_db()
    q = clean(request.args.get("q"), 80)
    status = request.args.get("status", "")
    pay = request.args.get("payment", "")
    dfrom, dto = clean(request.args.get("from"), 10), clean(request.args.get("to"), 10)
    where, args = [], []
    if q:
        where.append("(o.number LIKE ? ESCAPE '\\' OR o.email LIKE ? ESCAPE '\\' OR o.ship_name LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 3
    if status in orders_svc.STATUSES:
        where.append("o.status=?")
        args.append(status)
    if pay in ("unpaid", "paid", "failed", "refunded"):
        where.append("o.payment_status=?")
        args.append(pay)
    if dfrom:
        where.append("date(o.created_at) >= ?")
        args.append(dfrom)
    if dto:
        where.append("date(o.created_at) <= ?")
        args.append(dto)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.execute(f"SELECT COUNT(*) FROM orders o {clause}", args).fetchone()[0]
    per, page = 20, to_int(request.args.get("page"), 1, 1, 100000)
    rows = db.execute(
        f"SELECT o.*, (SELECT COALESCE(SUM(quantity),0) FROM order_items WHERE order_id=o.id) AS n_items "
        f"FROM orders o {clause} ORDER BY o.id DESC LIMIT ? OFFSET ?", args + [per, (page - 1) * per]).fetchall()
    return render_template("admin/orders.html", orders=rows, total=total, page=page, pages=max(1, -(-total // per)),
                           f={"q": q, "status": status, "payment": pay, "from": dfrom, "to": dto},
                           statuses=orders_svc.STATUSES)


def _order_or_404(db, order_id):
    o = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if o is None:
        abort(404)
    return o


@bp.route("/orders/<int:order_id>")
@staff_required("orders")
def order_detail(order_id):
    db = get_db()
    o = _order_or_404(db, order_id)
    customer = db.execute("SELECT * FROM customers WHERE id=?", (o["customer_id"],)).fetchone() if o["customer_id"] else None
    return render_template("admin/order.html", o=o, customer=customer, items=orders_svc.get_items(db, order_id),
                           history=orders_svc.get_history(db, order_id), payments=orders_svc.get_payments(db, order_id),
                           allowed=sorted(orders_svc.TRANSITIONS[o["status"]], key=orders_svc.STATUSES.index))


@bp.route("/orders/<int:order_id>/status", methods=["POST"])
@staff_required("orders")
def order_status(order_id):
    db = get_db()
    _order_or_404(db, order_id)
    try:
        orders_svc.change_status(db, order_id, request.form.get("status", ""), g.user["id"], clean(request.form.get("note"), 300))
        flash("Order status updated.", "success")
    except orders_svc.OrderStateError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.route("/orders/<int:order_id>/shipping", methods=["POST"])
@staff_required("orders")
def order_shipping(order_id):
    db = get_db()
    o = _order_or_404(db, order_id)
    f = request.form
    vals = {k: clean(f.get(k), n) for k, n in [("carrier", 60), ("tracking_number", 80), ("admin_note", 1000)]}
    if o["status"] in ("pending", "confirmed", "processing"):  # address editable until it ships
        addr = {k: clean(f.get(k), n) for k, n in [("ship_name", 120), ("ship_line1", 160), ("ship_line2", 160),
                                                    ("ship_city", 100), ("ship_region", 100), ("ship_postal", 20),
                                                    ("ship_country", 80)]}
        if len(addr["ship_name"]) < 2 or len(addr["ship_line1"]) < 3 or not addr["ship_city"] or not addr["ship_country"]:
            flash("Name, street, city and country are required.", "error")
            return redirect(url_for("admin.order_detail", order_id=order_id))
        vals.update(addr)
    sets = ", ".join(f"{k}=?" for k in vals)
    db.execute(f"UPDATE orders SET {sets}, updated_at=datetime('now') WHERE id=?", list(vals.values()) + [order_id])
    flash("Shipping information saved.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


# ---- customers --------------------------------------------------------------------------------
@bp.route("/customers")
@staff_required("customers")
def customers():
    db = get_db()
    q = clean(request.args.get("q"), 80)
    where, args = "", []
    if q:
        where = ("WHERE c.email LIKE ? ESCAPE '\\' OR c.first_name LIKE ? ESCAPE '\\' OR c.last_name LIKE ? ESCAPE '\\' "
                 "OR (c.first_name || ' ' || c.last_name) LIKE ? ESCAPE '\\'")
        args = [_like(q)] * 4
    total = db.execute(f"SELECT COUNT(*) FROM customers c {where}", args).fetchone()[0]
    per, page = 20, to_int(request.args.get("page"), 1, 1, 100000)
    rows = db.execute(
        f"SELECT c.*, u.is_active, (SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id) AS n_orders, "
        f"(SELECT COALESCE(SUM(total_cents),0) FROM orders o WHERE o.customer_id=c.id AND o.status IN {SALE_STATUSES}) AS spent "
        f"FROM customers c LEFT JOIN users u ON u.id=c.user_id {where} ORDER BY c.id DESC LIMIT ? OFFSET ?",
        args + [per, (page - 1) * per]).fetchall()
    return render_template("admin/customers.html", customers=rows, total=total, q=q, page=page,
                           pages=max(1, -(-total // per)))


@bp.route("/customers/<int:customer_id>")
@staff_required("customers")
def customer_detail(customer_id):
    db = get_db()
    c = db.execute("SELECT c.*, u.is_active, u.last_login_at FROM customers c LEFT JOIN users u ON u.id=c.user_id WHERE c.id=?",
                   (customer_id,)).fetchone()
    if c is None:
        abort(404)
    return render_template(
        "admin/customer.html", c=c,
        orders=db.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC", (customer_id,)).fetchall(),
        addresses=db.execute("SELECT * FROM addresses WHERE customer_id=? ORDER BY is_default DESC, id", (customer_id,)).fetchall(),
        spent=db.execute(f"SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE customer_id=? AND status IN {SALE_STATUSES}",
                         (customer_id,)).fetchone()[0])


@bp.route("/customers/<int:customer_id>/toggle", methods=["POST"])
@staff_required("customers")
def customer_toggle(customer_id):
    db = get_db()
    c = db.execute("SELECT user_id FROM customers WHERE id=?", (customer_id,)).fetchone()
    if c is None or c["user_id"] is None:
        abort(404)
    db.execute("UPDATE users SET is_active = 1 - is_active WHERE id=?", (c["user_id"],))
    flash("Account status updated.", "success")
    return redirect(url_for("admin.customer_detail", customer_id=customer_id))


# ---- newsletter -------------------------------------------------------------------------------
@bp.route("/newsletter")
@staff_required("customers")
def newsletter():
    rows = get_db().execute("SELECT * FROM newsletter_subscribers ORDER BY id DESC").fetchall()
    return render_template("admin/newsletter.html", subscribers=rows)


@bp.route("/newsletter.csv")
@staff_required("customers")
def newsletter_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "subscribed_at"])
    for r in get_db().execute("SELECT email, created_at FROM newsletter_subscribers ORDER BY id"):
        email = r["email"]
        w.writerow([("'" + email) if email[:1] in "=+-@" else email, r["created_at"]])  # CSV-injection guard
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=subscribers.csv"})


@bp.route("/newsletter/<int:sub_id>/delete", methods=["POST"])
@staff_required("customers")
def newsletter_delete(sub_id):
    get_db().execute("DELETE FROM newsletter_subscribers WHERE id=?", (sub_id,))
    flash("Subscriber removed.", "info")
    return redirect(url_for("admin.newsletter"))
