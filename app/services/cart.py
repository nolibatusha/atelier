"""Server-side persistent cart (keyed by an HttpOnly cookie token)."""
import secrets

from ..db import transaction


class CartError(Exception):
    pass


def find_by_token(db, token):
    if not token:
        return None
    return db.execute("SELECT * FROM carts WHERE token=?", (token,)).fetchone()


def create(db, customer_id=None):
    token = secrets.token_urlsafe(24)
    cur = db.execute("INSERT INTO carts(token, customer_id) VALUES(?,?)", (token, customer_id))
    return db.execute("SELECT * FROM carts WHERE id=?", (cur.lastrowid,)).fetchone()


def _touch(db, cart_id):
    db.execute("UPDATE carts SET updated_at=datetime('now') WHERE id=?", (cart_id,))


def count(db, cart_id):
    return db.execute("SELECT COALESCE(SUM(quantity),0) FROM cart_items WHERE cart_id=?", (cart_id,)).fetchone()[0]


def _variant(db, variant_id):
    v = db.execute(
        "SELECT v.*, p.name AS product_name, p.is_published FROM product_variants v "
        "JOIN products p ON p.id=v.product_id WHERE v.id=?",
        (variant_id,),
    ).fetchone()
    if v is None or not v["is_active"] or not v["is_published"]:
        raise CartError("That item is no longer available.")
    return v


def add_item(db, cart_id, variant_id, qty, max_line):
    if qty < 1:
        raise CartError("Quantity must be at least 1.")
    with transaction(db):
        v = _variant(db, variant_id)
        if v["stock"] <= 0:
            raise CartError(f"{v['product_name']} is sold out in this size/colour.")
        row = db.execute(
            "SELECT id, quantity FROM cart_items WHERE cart_id=? AND variant_id=?", (cart_id, variant_id)
        ).fetchone()
        new_qty = (row["quantity"] if row else 0) + qty
        limit = min(v["stock"], max_line)
        if new_qty > limit:
            raise CartError(
                f"Only {limit} available — you already have {row['quantity'] if row else 0} in your cart."
                if row else f"Only {limit} available."
            )
        if row:
            db.execute("UPDATE cart_items SET quantity=? WHERE id=?", (new_qty, row["id"]))
        else:
            db.execute("INSERT INTO cart_items(cart_id, variant_id, quantity) VALUES(?,?,?)", (cart_id, variant_id, new_qty))
        _touch(db, cart_id)


def _item(db, cart_id, item_id):
    row = db.execute("SELECT * FROM cart_items WHERE id=? AND cart_id=?", (item_id, cart_id)).fetchone()
    if row is None:
        raise CartError("That item isn't in your cart.")
    return row


def set_quantity(db, cart_id, item_id, qty, max_line):
    with transaction(db):
        item = _item(db, cart_id, item_id)
        if qty <= 0:
            db.execute("DELETE FROM cart_items WHERE id=?", (item_id,))
            return
        v = _variant(db, item["variant_id"])
        limit = min(v["stock"], max_line)
        if qty > limit:
            raise CartError(f"Only {limit} available for {v['product_name']}.")
        db.execute("UPDATE cart_items SET quantity=? WHERE id=?", (qty, item_id))
        _touch(db, cart_id)


def remove_item(db, cart_id, item_id):
    db.execute("DELETE FROM cart_items WHERE id=? AND cart_id=?", (item_id, cart_id))
    _touch(db, cart_id)


def change_variant(db, cart_id, item_id, new_variant_id, max_line):
    with transaction(db):
        item = _item(db, cart_id, item_id)
        old = db.execute("SELECT product_id FROM product_variants WHERE id=?", (item["variant_id"],)).fetchone()
        new = _variant(db, new_variant_id)
        if old is None or old["product_id"] != new["product_id"]:
            raise CartError("Invalid option.")
        if new_variant_id == item["variant_id"]:
            return
        dup = db.execute(
            "SELECT id, quantity FROM cart_items WHERE cart_id=? AND variant_id=?", (cart_id, new_variant_id)
        ).fetchone()
        qty = item["quantity"] + (dup["quantity"] if dup else 0)
        limit = min(new["stock"], max_line)
        if new["stock"] <= 0:
            raise CartError("That option is sold out.")
        if qty > limit:
            raise CartError(f"Only {limit} available in that option.")
        if dup:
            db.execute("UPDATE cart_items SET quantity=? WHERE id=?", (qty, dup["id"]))
            db.execute("DELETE FROM cart_items WHERE id=?", (item_id,))
        else:
            db.execute("UPDATE cart_items SET variant_id=? WHERE id=?", (new_variant_id, item_id))
        _touch(db, cart_id)


def fix_to_availability(db, cart_id):
    """Drop unavailable lines and clamp quantities to stock. Returns number of changes."""
    changed = 0
    with transaction(db):
        rows = db.execute(
            "SELECT ci.id, ci.quantity, v.stock, v.is_active, p.is_published FROM cart_items ci "
            "JOIN product_variants v ON v.id=ci.variant_id JOIN products p ON p.id=v.product_id "
            "WHERE ci.cart_id=?",
            (cart_id,),
        ).fetchall()
        for r in rows:
            if not r["is_active"] or not r["is_published"] or r["stock"] <= 0:
                db.execute("DELETE FROM cart_items WHERE id=?", (r["id"],))
                changed += 1
            elif r["quantity"] > r["stock"]:
                db.execute("UPDATE cart_items SET quantity=? WHERE id=?", (r["stock"], r["id"]))
                changed += 1
    return changed


def merge(db, target_id, source_id):
    """Move source cart lines into target (summing quantities), then delete source."""
    if target_id == source_id:
        return
    with transaction(db):
        for r in db.execute("SELECT variant_id, quantity FROM cart_items WHERE cart_id=?", (source_id,)).fetchall():
            db.execute(
                "INSERT INTO cart_items(cart_id, variant_id, quantity) VALUES(?,?,?) "
                "ON CONFLICT(cart_id, variant_id) DO UPDATE SET quantity = quantity + excluded.quantity",
                (target_id, r["variant_id"], r["quantity"]),
            )
        db.execute("DELETE FROM carts WHERE id=?", (source_id,))
