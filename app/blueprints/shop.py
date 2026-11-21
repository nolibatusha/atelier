"""Public storefront: home, catalogue, product pages, info pages, newsletter, media."""
from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, url_for)

from ..db import get_db
from ..security import rate_limit
from ..services import catalog
from ..services import media as media_svc
from ..util import clean, safe_next, to_int, valid_email

bp = Blueprint("shop", __name__)


@bp.route("/")
def home():
    db = get_db()
    return render_template("shop/home.html", **catalog.home_data(db))


@bp.route("/shop")
def shop():
    db = get_db()
    args = request.args
    f = {
        "q": clean(args.get("q"), 80),
        "category": clean(args.get("category"), 80),
        "collection": clean(args.get("collection"), 80),
        "min": clean(args.get("min"), 12),
        "max": clean(args.get("max"), 12),
        "sizes": [clean(x, 30) for x in args.getlist("size")][:12],
        "colors": [clean(x, 40) for x in args.getlist("color")][:12],
        "availability": args.get("availability") if args.get("availability") in ("in_stock", "out_of_stock") else "",
        "sort": args.get("sort") if args.get("sort") in catalog.SORTS else "newest",
    }
    per_page = current_app.config["PER_PAGE"]
    page = to_int(args.get("page"), 1, 1, 10_000)
    products, total = catalog.list_products(db, f, page, per_page)
    pages = max(1, -(-total // per_page))
    opts = catalog.filter_options(db)
    heading = {"name": "Shop all", "description": ""}
    if f["category"]:
        row = db.execute("SELECT name, description FROM categories WHERE slug=?", (f["category"],)).fetchone()
        heading = row or heading
    if f["collection"]:
        row = db.execute("SELECT name, description FROM collections WHERE slug=?", (f["collection"],)).fetchone()
        heading = row or heading
    if f["q"]:
        heading = {"name": f"Search: “{f['q']}”", "description": ""}
    return render_template("shop/shop.html", products=products, total=total, f=f, page=min(page, pages),
                           pages=pages, opts=opts, heading=heading)


@bp.route("/collections/<slug>")
def collection(slug):
    return redirect(url_for("shop.shop", collection=slug))


@bp.route("/product/<slug>")
def product(slug):
    db = get_db()
    p = catalog.get_product(db, slug)
    if p is None:
        abort(404)
    variants = [{"id": v["id"], "size": v["size"], "color": v["color"], "stock": v["stock"]} for v in p["variants"]]
    return render_template("shop/product.html", p=p, variants=variants, related=catalog.related(db, p))


@bp.route("/pages/<slug>")
def page(slug):
    row = get_db().execute("SELECT * FROM pages WHERE slug=?", (slug,)).fetchone()
    if row is None:
        abort(404)
    return render_template("shop/page.html", page=row)


@bp.route("/newsletter", methods=["POST"])
@rate_limit("newsletter", 8, 600)
def newsletter():
    email = clean(request.form.get("email"), 254).lower()
    nxt = safe_next(request.form.get("next"), url_for("shop.home"))
    wants_json = request.headers.get("Accept", "").startswith("application/json")
    if request.form.get("website"):  # honeypot field: real users never fill it
        return jsonify(ok=True) if wants_json else redirect(nxt)
    if not valid_email(email):
        msg = "Please enter a valid email address."
        if wants_json:
            return jsonify(ok=False, message=msg), 400
        flash(msg, "error")
        return redirect(nxt)
    db = get_db()
    db.execute("INSERT OR IGNORE INTO newsletter_subscribers(email) VALUES(?)", (email,))
    msg = "Thank you — you're on the list."
    if wants_json:
        return jsonify(ok=True, message=msg)
    flash(msg, "success")
    return redirect(nxt)


@bp.route("/media/<path:filename>")
def media(filename):
    upload_dir = current_app.config["UPLOAD_DIR"]
    width = request.args.get("w", type=int)
    if width:
        cached = media_svc.variant(upload_dir, filename, width)
        if cached:
            filename = cached
    return send_from_directory(upload_dir, filename, max_age=60 * 60 * 24 * 30)


@bp.route("/healthz")
def healthz():
    get_db().execute("SELECT 1")
    return jsonify(status="ok")
