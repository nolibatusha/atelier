"""Stock changes. Every mutation is a conditional UPDATE (never read-modify-write in Python) and
leaves a row in inventory_movements, so stock can never go negative and history is complete."""
from ..db import transaction


class InsufficientStock(Exception):
    pass


def variant_desc(v):
    return " / ".join(x for x in (v["size"], v["color"]) if x)


def adjust(db, variant_id, delta, reason, note="", user_id=None, order_id=None):
    """Atomically add `delta` (may be negative). Returns the new stock level."""
    if delta == 0:
        return db.execute("SELECT stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()["stock"]
    with transaction(db):
        v = db.execute(
            "SELECT v.*, p.name AS product_name FROM product_variants v "
            "JOIN products p ON p.id=v.product_id WHERE v.id=?",
            (variant_id,),
        ).fetchone()
        if v is None:
            raise LookupError("Variant not found")
        cur = db.execute(
            "UPDATE product_variants SET stock = stock + ? WHERE id=? AND stock + ? >= 0",
            (delta, variant_id, delta),
        )
        if cur.rowcount != 1:
            raise InsufficientStock(f"Not enough stock for {v['product_name']} ({variant_desc(v)}).")
        after = db.execute("SELECT stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()["stock"]
        db.execute(
            "INSERT INTO inventory_movements(variant_id, sku, product_name, variant_desc, delta, stock_after,"
            " reason, note, order_id, user_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (variant_id, v["sku"], v["product_name"], variant_desc(v), delta, after, reason, note, order_id, user_id),
        )
        return after


def set_stock(db, variant_id, new_qty, reason="correction", note="", user_id=None):
    """Set an absolute quantity (stocktake). Delta is computed inside the transaction."""
    with transaction(db):
        cur = db.execute("SELECT stock FROM product_variants WHERE id=?", (variant_id,)).fetchone()
        if cur is None:
            raise LookupError("Variant not found")
        return adjust(db, variant_id, new_qty - cur["stock"], reason, note, user_id)


def low_stock(db, limit=50):
    return db.execute(
        "SELECT v.*, p.name AS product_name, p.id AS product_id FROM product_variants v "
        "JOIN products p ON p.id=v.product_id "
        "WHERE v.is_active=1 AND v.stock <= v.low_stock_threshold ORDER BY v.stock, p.name LIMIT ?",
        (limit,),
    ).fetchall()
