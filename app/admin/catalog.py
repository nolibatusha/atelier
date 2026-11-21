"""Products, categories/collections, inventory, discounts."""
from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

from ..db import get_db, transaction
from ..security import staff_required
from ..services import inventory, media
from ..services import products as products_svc
from ..util import clean, clean_multiline, cents_to_input, parse_money, slugify, to_int, unique_slug
from . import bp


def _like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ---- products ---------------------------------------------------------------------------------
@bp.route("/products")
@staff_required("products")
def products():
    db = get_db()
    q, cat, st = clean(request.args.get("q"), 80), to_int(request.args.get("category")), request.args.get("status", "")
    where, args = [], []
    if q:
        where.append("(p.name LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND v.sku LIKE ? ESCAPE '\\'))")
        args += [_like(q)] * 2
    if cat:
        where.append("p.category_id=?")
        args.append(cat)
    if st == "published":
        where.append("p.is_published=1")
    elif st == "draft":
        where.append("p.is_published=0")
    elif st == "featured":
        where.append("p.is_featured=1")
    elif st == "low":
        where.append("EXISTS (SELECT 1 FROM product_variants v WHERE v.product_id=p.id AND v.is_active=1 AND v.stock<=v.low_stock_threshold)")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.execute(f"SELECT COUNT(*) FROM products p {clause}", args).fetchone()[0]
    per, page = 20, to_int(request.args.get("page"), 1, 1, 100000)
    rows = db.execute(
        f"SELECT p.*, c.name AS category_name, "
        f"(SELECT filename FROM product_images WHERE product_id=p.id ORDER BY position, id LIMIT 1) AS image, "
        f"(SELECT COALESCE(SUM(stock),0) FROM product_variants WHERE product_id=p.id AND is_active=1) AS stock_total, "
        f"(SELECT COUNT(*) FROM product_variants WHERE product_id=p.id AND is_active=1) AS n_variants "
        f"FROM products p LEFT JOIN categories c ON c.id=p.category_id {clause} ORDER BY p.id DESC LIMIT ? OFFSET ?",
        args + [per, (page - 1) * per]).fetchall()
    cats = db.execute("SELECT id, name FROM categories ORDER BY sort_order, name").fetchall()
    return render_template("admin/products.html", products=rows, total=total, page=page, pages=max(1, -(-total // per)),
                           f={"q": q, "category": cat, "status": st}, categories=cats)


def _form_context(db, p, variants, images, errors=None):
    return dict(
        p=p, variants=variants, images=images, errors=errors or [],
        categories=db.execute("SELECT id, name FROM categories ORDER BY sort_order, name").fetchall(),
        collections=db.execute("SELECT id, name FROM collections ORDER BY sort_order, name").fetchall())


@bp.route("/products/new", methods=["GET", "POST"])
@staff_required("products")
def product_new():
    return _product_form(None)


@bp.route("/products/<int:product_id>", methods=["GET", "POST"])
@staff_required("products")
def product_edit(product_id):
    return _product_form(product_id)


def _product_form(product_id):
    db = get_db()
    existing = None
    if product_id is not None:
        existing = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if existing is None:
            abort(404)
    if request.method == "POST":
        pid, errors = products_svc.save_product(
            db, request.form, request.files.getlist("images"), current_app.config["UPLOAD_DIR"],
            current_app.config["MAX_IMAGE_BYTES"], g.user["id"], product_id)
        if not errors:
            flash("Product saved.", "success")
            return redirect(url_for("admin.product_edit", product_id=pid))
        f = request.form
        p = dict(existing) if existing else {}
        p.update(id=product_id, name=f.get("name", ""), slug=f.get("slug", ""), description=f.get("description", ""),
                 details=f.get("details", ""), category_id=to_int(f.get("category_id")), price_in=f.get("price", ""),
                 sale_in=f.get("sale_price", ""), is_featured=bool(f.get("is_featured")),
                 is_published=bool(f.get("is_published")), collection_ids=[to_int(x) for x in f.getlist("collections")])
        variants = [dict(id=v["id"], size=v["size"], color=v["color"], color_hex=v["color_hex"], sku=v["sku"],
                         stock=v["stock"] if v["stock"] is not None else 0, low_stock_threshold=v["low"], is_active=v["active"])
                    for v in products_svc.parse_variants(f)]
        images = db.execute("SELECT * FROM product_images WHERE product_id=? ORDER BY position, id", (product_id,)).fetchall() if product_id else []
        return render_template("admin/product_form.html", **_form_context(db, p, variants, images, errors)), 422

    if existing:
        p = dict(existing)
        p["price_in"], p["sale_in"] = cents_to_input(p["price_cents"]), cents_to_input(p["sale_price_cents"])
        p["collection_ids"] = [r[0] for r in db.execute("SELECT collection_id FROM product_collections WHERE product_id=?", (product_id,))]
        variants = db.execute("SELECT * FROM product_variants WHERE product_id=? ORDER BY id", (product_id,)).fetchall()
        images = db.execute("SELECT * FROM product_images WHERE product_id=? ORDER BY position, id", (product_id,)).fetchall()
    else:
        p = dict(id=None, name="", slug="", description="", details="", category_id=None, price_in="", sale_in="",
                 is_featured=False, is_published=False, collection_ids=[])
        variants, images = [], []
    return render_template("admin/product_form.html", **_form_context(db, p, variants, images))


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@staff_required("products")
def product_toggle(product_id):
    db = get_db()
    field = {"publish": "is_published", "feature": "is_featured"}.get(request.form.get("field"))
    if field is None:
        abort(400)
    if field == "is_published":
        ok = db.execute("SELECT 1 FROM product_variants WHERE product_id=? AND is_active=1", (product_id,)).fetchone()
        cur = db.execute("SELECT is_published FROM products WHERE id=?", (product_id,)).fetchone()
        if cur is None:
            abort(404)
        if not cur["is_published"] and not ok:
            flash("Add an active variant before publishing this product.", "error")
            return redirect(request.referrer or url_for("admin.products"))
    db.execute(f"UPDATE products SET {field} = 1 - {field}, updated_at=datetime('now') WHERE id=?", (product_id,))
    return redirect(request.referrer or url_for("admin.products"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@staff_required("products")
def product_delete(product_id):
    db = get_db()
    if db.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone() is None:
        abort(404)
    products_svc.delete_product(db, current_app.config["UPLOAD_DIR"], product_id)
    flash("Product deleted. Past orders keep their product details.", "info")
    return redirect(url_for("admin.products"))


# ---- categories & collections -----------------------------------------------------------------
KINDS = {"categories": "category", "collections": "collection"}


@bp.route("/taxonomy/<kind>", methods=["GET", "POST"])
@staff_required("products")
def taxonomy(kind):
    if kind not in KINDS:
        abort(404)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        row_id = to_int(request.form.get("id"))
        if action == "delete" and row_id:
            db.execute(f"DELETE FROM {kind} WHERE id=?", (row_id,))
            flash(f"{KINDS[kind].title()} deleted (products were kept).", "info")
        else:
            name = clean(request.form.get("name"), 80)
            if not name:
                flash("A name is required.", "error")
                return redirect(url_for("admin.taxonomy", kind=kind))
            image = None
            fs = request.files.get("image")
            if fs and fs.filename:
                try:
                    image = media.save_image(fs, current_app.config["UPLOAD_DIR"], current_app.config["MAX_IMAGE_BYTES"])
                except media.UploadError as e:
                    flash(str(e), "error")
                    return redirect(url_for("admin.taxonomy", kind=kind))
            vals = dict(name=name, description=clean_multiline(request.form.get("description"), 600),
                        sort_order=to_int(request.form.get("sort_order"), 0, -1000, 1000),
                        is_active=1 if request.form.get("is_active") else 0)
            if kind == "collections":
                vals["is_featured"] = 1 if request.form.get("is_featured") else 0
            if image:
                vals["image"] = image
            if row_id and db.execute(f"SELECT 1 FROM {kind} WHERE id=?", (row_id,)).fetchone():
                sets = ", ".join(f"{k}=?" for k in vals)
                db.execute(f"UPDATE {kind} SET {sets} WHERE id=?", list(vals.values()) + [row_id])
            else:
                vals["slug"] = unique_slug(db, kind, name)
                cols = ", ".join(vals)
                db.execute(f"INSERT INTO {kind}({cols}) VALUES({','.join('?' * len(vals))})", list(vals.values()))
            flash(f"{KINDS[kind].title()} saved.", "success")
        return redirect(url_for("admin.taxonomy", kind=kind))
    count_sql = ("(SELECT COUNT(*) FROM products p WHERE p.category_id=t.id)" if kind == "categories"
                 else "(SELECT COUNT(*) FROM product_collections pc WHERE pc.collection_id=t.id)")
    rows = db.execute(f"SELECT t.*, {count_sql} AS n_products FROM {kind} t ORDER BY sort_order, name").fetchall()
    return render_template("admin/taxonomy.html", kind=kind, label=KINDS[kind], rows=rows)


# ---- inventory --------------------------------------------------------------------------------
@bp.route("/inventory")
@staff_required("inventory")
def inventory_list():
    db = get_db()
    q, flt = clean(request.args.get("q"), 80), request.args.get("filter", "")
    where, args = ["1=1"], []
    if q:
        where.append("(p.name LIKE ? ESCAPE '\\' OR v.sku LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 2
    if flt == "low":
        where.append("v.is_active=1 AND v.stock > 0 AND v.stock <= v.low_stock_threshold")
    elif flt == "out":
        where.append("v.is_active=1 AND v.stock = 0")
    clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM product_variants v JOIN products p ON p.id=v.product_id WHERE {clause}", args).fetchone()[0]
    per, page = 30, to_int(request.args.get("page"), 1, 1, 100000)
    rows = db.execute(
        f"SELECT v.*, p.name AS product_name, p.id AS product_id FROM product_variants v JOIN products p ON p.id=v.product_id "
        f"WHERE {clause} ORDER BY (v.stock <= v.low_stock_threshold) DESC, p.name, v.id LIMIT ? OFFSET ?",
        args + [per, (page - 1) * per]).fetchall()
    summary = db.execute(
        "SELECT SUM(CASE WHEN is_active=1 AND stock=0 THEN 1 ELSE 0 END) AS out_n, "
        "SUM(CASE WHEN is_active=1 AND stock>0 AND stock<=low_stock_threshold THEN 1 ELSE 0 END) AS low_n, "
        "COALESCE(SUM(stock),0) AS units FROM product_variants").fetchone()
    return render_template("admin/inventory.html", rows=rows, total=total, page=page, pages=max(1, -(-total // per)),
                           f={"q": q, "filter": flt}, summary=summary)


@bp.route("/inventory/adjust", methods=["POST"])
@staff_required("inventory")
def inventory_adjust():
    db = get_db()
    f = request.form
    vid, qty = to_int(f.get("variant_id")), to_int(f.get("qty"), None, -1_000_000, 1_000_000)
    mode, reason = f.get("mode", "add"), f.get("reason", "correction")
    if reason not in ("restock", "correction", "damaged", "return", "stocktake"):
        reason = "correction"
    nxt = request.form.get("next")
    back = nxt if nxt and nxt.startswith("/admin/") else url_for("admin.inventory_list")
    if not vid or qty is None:
        flash("Enter a whole number quantity.", "error")
        return redirect(back)
    try:
        if mode == "set":
            if qty < 0:
                raise ValueError("Stock can't be negative.")
            new = inventory.set_stock(db, vid, qty, reason, clean(f.get("note"), 200), g.user["id"])
        else:
            new = inventory.adjust(db, vid, qty, reason, clean(f.get("note"), 200), g.user["id"])
        flash(f"Stock updated — now {new} in stock.", "success")
    except inventory.InsufficientStock:
        flash("That adjustment would make stock negative.", "error")
    except (LookupError, ValueError) as e:
        flash(str(e), "error")
    return redirect(back)


@bp.route("/inventory/history")
@staff_required("inventory")
def inventory_history():
    db = get_db()
    q, reason = clean(request.args.get("q"), 80), clean(request.args.get("reason"), 30)
    where, args = ["1=1"], []
    if q:
        where.append("(m.sku LIKE ? ESCAPE '\\' OR m.product_name LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 2
    if reason:
        where.append("m.reason=?")
        args.append(reason)
    clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM inventory_movements m WHERE {clause}", args).fetchone()[0]
    per, page = 40, to_int(request.args.get("page"), 1, 1, 100000)
    rows = db.execute(
        f"SELECT m.*, u.name AS user_name, o.number AS order_number FROM inventory_movements m "
        f"LEFT JOIN users u ON u.id=m.user_id LEFT JOIN orders o ON o.id=m.order_id WHERE {clause} "
        f"ORDER BY m.id DESC LIMIT ? OFFSET ?", args + [per, (page - 1) * per]).fetchall()
    reasons = [r[0] for r in db.execute("SELECT DISTINCT reason FROM inventory_movements ORDER BY reason")]
    return render_template("admin/inventory_history.html", rows=rows, total=total, page=page,
                           pages=max(1, -(-total // per)), f={"q": q, "reason": reason}, reasons=reasons)


# ---- discounts --------------------------------------------------------------------------------
@bp.route("/discounts", methods=["GET", "POST"])
@staff_required("discounts")
def discounts():
    db = get_db()
    if request.method == "POST":
        f, action = request.form, request.form.get("action")
        did = to_int(f.get("id"))
        if action == "toggle" and did:
            db.execute("UPDATE discounts SET is_active = 1 - is_active WHERE id=?", (did,))
        elif action == "delete" and did:
            db.execute("DELETE FROM discounts WHERE id=?", (did,))
            flash("Discount deleted.", "info")
        elif action == "create":
            code = clean(f.get("code"), 40).upper().replace(" ", "")
            kind = f.get("kind") if f.get("kind") in ("percent", "fixed") else "percent"
            value = to_int(f.get("value"), None, 1, 100) if kind == "percent" else parse_money(f.get("value", ""))
            if kind == "fixed" and value == 0:
                value = None
            mn = parse_money(f.get("min_subtotal") or "0") or 0
            mx = to_int(f.get("max_uses"), None, 1, 10_000_000) if f.get("max_uses") else None
            if not code or value is None:
                flash("Enter a code and a valid value (percent 1–100, or an amount).", "error")
            elif db.execute("SELECT 1 FROM discounts WHERE code=?", (code,)).fetchone():
                flash("That code already exists.", "error")
            else:
                db.execute(
                    "INSERT INTO discounts(code, kind, value, min_subtotal_cents, max_uses, starts_on, ends_on) VALUES(?,?,?,?,?,?,?)",
                    (code, kind, value, mn, mx, clean(f.get("starts_on"), 10) or None, clean(f.get("ends_on"), 10) or None))
                flash(f"Discount {code} created.", "success")
        return redirect(url_for("admin.discounts"))
    return render_template("admin/discounts.html", rows=db.execute("SELECT * FROM discounts ORDER BY id DESC").fetchall())
