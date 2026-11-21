"""Read-side catalogue queries for the storefront."""
from ..util import parse_money

SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "One Size"]

PRICE_SQL = "COALESCE(p.sale_price_cents, p.price_cents)"
STOCK_SQL = "(SELECT COALESCE(SUM(v.stock),0) FROM product_variants v WHERE v.product_id=p.id AND v.is_active=1)"
SOLD_SQL = (
    "(SELECT COALESCE(SUM(oi.quantity),0) FROM order_items oi JOIN orders o ON o.id=oi.order_id "
    "WHERE oi.product_id=p.id AND o.status IN ('confirmed','processing','shipped','delivered'))"
)
CARD_COLS = (
    f"p.*, c.name AS category_name, c.slug AS category_slug, {STOCK_SQL} AS stock_total, {SOLD_SQL} AS sold, "
    "(julianday('now') - julianday(p.created_at) <= 21) AS is_new"
)
SORTS = {
    "newest": "p.created_at DESC, p.id DESC",
    "price_asc": f"{PRICE_SQL} ASC, p.id",
    "price_desc": f"{PRICE_SQL} DESC, p.id",
    "popular": "sold DESC, p.id DESC",
}


def _size_key(s):
    return SIZE_ORDER.index(s) if s in SIZE_ORDER else len(SIZE_ORDER)


def decorate(db, rows):
    """Turn product rows into dicts with images, colour swatches and badges for product cards."""
    items = [dict(r) for r in rows]
    if not items:
        return items
    ids = [i["id"] for i in items]
    marks = ",".join("?" * len(ids))
    imgs = {}
    for r in db.execute(f"SELECT product_id, filename FROM product_images WHERE product_id IN ({marks}) ORDER BY position, id", ids):
        imgs.setdefault(r["product_id"], []).append(r["filename"])
    cols = {}
    for r in db.execute(
        f"SELECT DISTINCT product_id, color, color_hex FROM product_variants "
        f"WHERE product_id IN ({marks}) AND is_active=1 AND color != '' ORDER BY id", ids):
        cols.setdefault(r["product_id"], []).append({"name": r["color"], "hex": r["color_hex"]})
    for i in items:
        pics = imgs.get(i["id"], [])
        i["image"] = pics[0] if pics else ""
        i["image2"] = pics[1] if len(pics) > 1 else ""
        i["colors"] = cols.get(i["id"], [])
        i["price"] = i["sale_price_cents"] if i["sale_price_cents"] is not None else i["price_cents"]
        i["on_sale"] = i["sale_price_cents"] is not None
        i["sold_out"] = i["stock_total"] <= 0
    return items


def list_products(db, f, page=1, per_page=12):
    where, args = ["p.is_published=1"], []
    q = (f.get("q") or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(p.name LIKE ? ESCAPE '\\' OR p.description LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\')")
        args += [like, like, like]
    if f.get("category"):
        where.append("c.slug=?")
        args.append(f["category"])
    if f.get("collection"):
        where.append("EXISTS (SELECT 1 FROM product_collections pc JOIN collections co ON co.id=pc.collection_id "
                     "WHERE pc.product_id=p.id AND co.slug=?)")
        args.append(f["collection"])
    lo, hi = parse_money(f.get("min") or ""), parse_money(f.get("max") or "")
    if lo is not None:
        where.append(f"{PRICE_SQL} >= ?")
        args.append(lo)
    if hi is not None:
        where.append(f"{PRICE_SQL} <= ?")
        args.append(hi)
    sizes, colors = f.get("sizes") or [], f.get("colors") or []
    if sizes or colors:
        cond, sub = ["v.product_id=p.id", "v.is_active=1", "v.stock>0"], []
        if sizes:
            cond.append(f"v.size IN ({','.join('?' * len(sizes))})")
            sub += sizes
        if colors:
            cond.append(f"v.color IN ({','.join('?' * len(colors))})")
            sub += colors
        where.append(f"EXISTS (SELECT 1 FROM product_variants v WHERE {' AND '.join(cond)})")
        args += sub
    avail = f.get("availability")
    if avail == "in_stock":
        where.append(f"{STOCK_SQL} > 0")
    elif avail == "out_of_stock":
        where.append(f"{STOCK_SQL} <= 0")

    base = "FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE " + " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
    order = SORTS.get(f.get("sort"), SORTS["newest"])
    page = max(1, page)
    rows = db.execute(
        f"SELECT {CARD_COLS} {base} ORDER BY {order} LIMIT ? OFFSET ?", args + [per_page, (page - 1) * per_page]
    ).fetchall()
    return decorate(db, rows), total


def filter_options(db):
    cats = db.execute(
        "SELECT c.slug, c.name, (SELECT COUNT(*) FROM products p WHERE p.category_id=c.id AND p.is_published=1) AS n "
        "FROM categories c WHERE c.is_active=1 ORDER BY c.sort_order, c.name").fetchall()
    colls = db.execute("SELECT slug, name FROM collections WHERE is_active=1 ORDER BY sort_order, name").fetchall()
    base = ("FROM product_variants v JOIN products p ON p.id=v.product_id "
            "WHERE p.is_published=1 AND v.is_active=1")
    sizes = sorted({r[0] for r in db.execute(f"SELECT DISTINCT v.size {base} AND v.size!=''")}, key=_size_key)
    colors = [dict(r) for r in db.execute(
        f"SELECT v.color AS name, MIN(v.color_hex) AS hex {base} AND v.color!='' GROUP BY v.color ORDER BY v.color")]
    return {"categories": cats, "collections": colls, "sizes": sizes, "colors": colors}


def get_product(db, slug, include_unpublished=False):
    sql = f"SELECT {CARD_COLS} FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.slug=?"
    if not include_unpublished:
        sql += " AND p.is_published=1"
    row = db.execute(sql, (slug,)).fetchone()
    if row is None:
        return None
    p = decorate(db, [row])[0]
    p["images"] = db.execute("SELECT * FROM product_images WHERE product_id=? ORDER BY position, id", (p["id"],)).fetchall()
    variants = db.execute(
        "SELECT * FROM product_variants WHERE product_id=? AND is_active=1 ORDER BY id", (p["id"],)).fetchall()
    p["variants"] = sorted(variants, key=lambda v: (v["color"], _size_key(v["size"])))
    p["sizes"] = sorted({v["size"] for v in variants if v["size"]}, key=_size_key)
    seen, colors = set(), []
    for v in variants:
        if v["color"] and v["color"] not in seen:
            seen.add(v["color"])
            colors.append({"name": v["color"], "hex": v["color_hex"]})
    p["colors"] = colors
    p["collections"] = db.execute(
        "SELECT co.* FROM collections co JOIN product_collections pc ON pc.collection_id=co.id "
        "WHERE pc.product_id=? AND co.is_active=1", (p["id"],)).fetchall()
    return p


def related(db, product, limit=4):
    rows = db.execute(
        f"SELECT {CARD_COLS} FROM products p LEFT JOIN categories c ON c.id=p.category_id "
        "WHERE p.is_published=1 AND p.id != ? AND (p.category_id = ? OR EXISTS ("
        "  SELECT 1 FROM product_collections a JOIN product_collections b ON a.collection_id=b.collection_id "
        "  WHERE a.product_id=p.id AND b.product_id=?)) "
        "ORDER BY (p.category_id = ?) DESC, p.created_at DESC LIMIT ?",
        (product["id"], product["category_id"], product["id"], product["category_id"], limit)).fetchall()
    return decorate(db, rows)


def home_data(db):
    new = db.execute(
        f"SELECT {CARD_COLS} FROM products p LEFT JOIN categories c ON c.id=p.category_id "
        "WHERE p.is_published=1 ORDER BY p.created_at DESC, p.id DESC LIMIT 8").fetchall()
    best = db.execute(
        f"SELECT {CARD_COLS} FROM products p LEFT JOIN categories c ON c.id=p.category_id "
        "WHERE p.is_published=1 ORDER BY sold DESC, p.is_featured DESC, p.id DESC LIMIT 4").fetchall()
    collections = db.execute(
        "SELECT * FROM collections WHERE is_active=1 AND is_featured=1 ORDER BY sort_order, id LIMIT 3").fetchall()
    return {"new": decorate(db, new), "best": decorate(db, best), "collections": collections}
