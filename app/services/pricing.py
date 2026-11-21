"""Single source of truth for prices, discounts, shipping and tax. The browser never supplies
amounts: cart page, checkout page and order creation all call quote() on database values."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

LINE_SQL = """
SELECT ci.id AS item_id, ci.quantity, v.id AS variant_id, v.sku, v.size, v.color, v.color_hex,
       v.stock, v.is_active AS variant_active,
       p.id AS product_id, p.slug, p.name, p.price_cents, p.sale_price_cents, p.is_published,
       (SELECT filename FROM product_images WHERE product_id=p.id ORDER BY position, id LIMIT 1) AS image
FROM cart_items ci
JOIN product_variants v ON v.id = ci.variant_id
JOIN products p ON p.id = v.product_id
WHERE ci.cart_id = ? ORDER BY ci.id
"""


def unit_price(price_cents, sale_cents):
    return sale_cents if sale_cents is not None else price_cents


def cart_lines(db, cart_id):
    lines = []
    for r in db.execute(LINE_SQL, (cart_id,)):
        l = dict(r)
        unit = unit_price(r["price_cents"], r["sale_price_cents"])
        l["unit_cents"] = unit
        l["line_cents"] = unit * r["quantity"]
        l["compare_line_cents"] = r["price_cents"] * r["quantity"]
        if not r["is_published"] or not r["variant_active"] or r["stock"] <= 0:
            l["issue"], l["available"] = "unavailable", 0
        elif r["quantity"] > r["stock"]:
            l["issue"], l["available"] = "insufficient", r["stock"]
        else:
            l["issue"], l["available"] = None, r["stock"]
        lines.append(l)
    return lines


def active_shipping_methods(db):
    return db.execute("SELECT * FROM shipping_methods WHERE is_active=1 ORDER BY sort_order, id").fetchall()


def pick_shipping(db, method_id):
    methods = active_shipping_methods(db)
    for m in methods:
        if m["id"] == method_id:
            return m
    return methods[0] if methods else None


def validate_discount(db, code, subtotal_cents):
    """Returns (discount_row, error_message)."""
    code = (code or "").strip()
    if not code:
        return None, None
    d = db.execute("SELECT * FROM discounts WHERE code=?", (code,)).fetchone()
    today = date.today().isoformat()
    if d is None or not d["is_active"]:
        return None, "That discount code isn't valid."
    if d["starts_on"] and today < d["starts_on"]:
        return None, "That discount code isn't active yet."
    if d["ends_on"] and today > d["ends_on"]:
        return None, "That discount code has expired."
    if d["max_uses"] is not None and d["used_count"] >= d["max_uses"]:
        return None, "That discount code has reached its usage limit."
    if subtotal_cents < d["min_subtotal_cents"]:
        return None, "Spend a little more to use this code (minimum order not reached)."
    return d, None


def _round(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quote(db, lines, shipping_method, discount_code, settings):
    purchasable = [l for l in lines if l["issue"] != "unavailable"]
    subtotal = sum(l["line_cents"] for l in purchasable)
    savings = sum(l["compare_line_cents"] - l["line_cents"] for l in purchasable)

    d, d_err = validate_discount(db, discount_code, subtotal)
    discount = 0
    if d:
        discount = subtotal * d["value"] // 100 if d["kind"] == "percent" else min(d["value"], subtotal)
        discount = min(discount, subtotal)
    after_discount = subtotal - discount

    shipping = 0
    if purchasable and shipping_method is not None:
        free_over = shipping_method["free_over_cents"]
        shipping = 0 if (free_over is not None and after_discount >= free_over) else shipping_method["price_cents"]

    tax, inclusive = 0, bool(settings.get("tax_inclusive", True))
    rate = Decimal(str(settings.get("tax_rate") or 0))
    base = after_discount + shipping
    if settings.get("tax_enabled") and rate > 0 and base > 0:
        tax = _round(Decimal(base) * rate / (100 + rate)) if inclusive else _round(Decimal(base) * rate / 100)
    total = base if (inclusive or not settings.get("tax_enabled")) else base + tax

    return {
        "lines": lines,
        "count": sum(l["quantity"] for l in purchasable),
        "subtotal": subtotal,
        "savings": savings,
        "discount": discount,
        "discount_code": d["code"] if d else "",
        "discount_error": d_err,
        "shipping": shipping,
        "shipping_method": shipping_method,
        "tax": tax,
        "tax_inclusive": inclusive and bool(settings.get("tax_enabled")),
        "total": total,
        "blocking": any(l["issue"] for l in lines) or not lines,
        "amount_to_free_shipping": (
            max(0, shipping_method["free_over_cents"] - after_discount)
            if shipping_method is not None and shipping_method["free_over_cents"] is not None and purchasable
            else None
        ),
    }
