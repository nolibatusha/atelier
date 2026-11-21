"""Admin-side product persistence: product row, collections, variants (with stock ledger) and images."""
import re
import sqlite3

_HEX = re.compile(r"#[0-9a-fA-F]{6}")

from ..db import transaction
from ..util import clean, clean_multiline, parse_money, slugify, to_int, unique_slug
from . import inventory, media


def _auto_sku(db, slug, size, color, taken):
    base = "-".join(x for x in (slug.upper()[:14], slugify(size).upper(), slugify(color).upper()) if x)
    sku, n = base, 1
    while sku in taken or db.execute("SELECT 1 FROM product_variants WHERE sku=?", (sku,)).fetchone():
        n += 1
        sku = f"{base}-{n}"
    taken.add(sku)
    return sku


def parse_variants(form):
    rows = []
    ids = form.getlist("v_id")
    for i in range(len(ids)):
        g = lambda name: (form.getlist(name) + [""] * len(ids))[i]
        size, color = clean(g("v_size"), 30), clean(g("v_color"), 40)
        if not (size or color or g("v_sku").strip() or g("v_stock").strip()):
            continue  # blank template row
        hexv = clean(g("v_hex"), 7)
        rows.append({
            "id": to_int(ids[i]),
            "size": size or ("" if color else "One Size"),
            "color": color,
            "color_hex": hexv if _HEX.fullmatch(hexv) else "",
            "sku": clean(g("v_sku"), 60).upper(),
            "stock": to_int(g("v_stock") or 0, default=None, lo=0, hi=1_000_000),
            "low": to_int(g("v_low") or 3, default=3, lo=0, hi=10_000),
            "active": 0 if g("v_active") == "0" else 1,
        })
    return rows


def save_product(db, form, files, upload_dir, max_image_bytes, user_id, product_id=None):
    """Validate and persist. Returns (product_id, errors). Nothing is written when errors exist."""
    errors = []
    name = clean(form.get("name"), 160)
    if not name:
        errors.append("Product name is required.")
    price = parse_money(form.get("price", ""))
    if price is None:
        errors.append("Enter a valid price.")
    sale_raw = (form.get("sale_price") or "").strip()
    sale = parse_money(sale_raw) if sale_raw else None
    if sale_raw and sale is None:
        errors.append("Enter a valid sale price (or leave blank).")
    if sale is not None and price is not None and sale >= price:
        errors.append("The sale price must be lower than the regular price.")
    category_id = to_int(form.get("category_id"))
    if category_id and not db.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone():
        category_id = None
    collection_ids = [c for c in (to_int(x) for x in form.getlist("collections")) if c]
    publish = 1 if form.get("is_published") else 0

    variants = parse_variants(form)
    seen = set()
    for v in variants:
        if v["stock"] is None:
            errors.append("Stock must be a whole number (0 or more).")
            break
        key = (v["size"].lower(), v["color"].lower())
        if key in seen:
            errors.append(f"Duplicate variant: {v['size']} {v['color']}".strip())
            break
        seen.add(key)
    if publish and not any(v["active"] for v in variants):
        errors.append("Add at least one active variant before publishing.")
    if errors:
        return product_id, errors

    # Save uploads first; clean them up if the database write fails.
    new_files, upload_errors = [], []
    for fs in files:
        if fs and fs.filename:
            try:
                new_files.append(media.save_image(fs, upload_dir, max_image_bytes))
            except media.UploadError as e:
                upload_errors.append(f"{fs.filename}: {e}")
    if upload_errors:
        for n in new_files:
            media.delete_file(upload_dir, n)
        return product_id, upload_errors

    removed_files = []
    try:
        with transaction(db):
            slug = unique_slug(db, "products", form.get("slug") or name, product_id)
            fields = (name, slug, clean_multiline(form.get("description"), 6000),
                      clean_multiline(form.get("details"), 3000), category_id, price, sale,
                      1 if form.get("is_featured") else 0, publish)
            if product_id is None:
                cur = db.execute(
                    "INSERT INTO products(name, slug, description, details, category_id, price_cents, sale_price_cents,"
                    " is_featured, is_published) VALUES(?,?,?,?,?,?,?,?,?)", fields)
                product_id = cur.lastrowid
            else:
                db.execute(
                    "UPDATE products SET name=?, slug=?, description=?, details=?, category_id=?, price_cents=?,"
                    " sale_price_cents=?, is_featured=?, is_published=?, updated_at=datetime('now') WHERE id=?",
                    fields + (product_id,))

            db.execute("DELETE FROM product_collections WHERE product_id=?", (product_id,))
            for cid in collection_ids:
                db.execute("INSERT OR IGNORE INTO product_collections(product_id, collection_id) "
                           "SELECT ?, id FROM collections WHERE id=?", (product_id, cid))

            # variants
            existing = {r["id"]: r for r in db.execute("SELECT * FROM product_variants WHERE product_id=?", (product_id,))}
            taken, kept = set(), set()
            for v in variants:
                if v["id"] in existing:
                    old = existing[v["id"]]
                    sku = v["sku"] or old["sku"]
                    db.execute(
                        "UPDATE product_variants SET size=?, color=?, color_hex=?, sku=?, low_stock_threshold=?, is_active=? WHERE id=?",
                        (v["size"], v["color"], v["color_hex"], sku, v["low"], v["active"], v["id"]))
                    if v["stock"] != old["stock"]:
                        inventory.adjust(db, v["id"], v["stock"] - old["stock"], "admin_edit", "Edited on product page", user_id)
                    kept.add(v["id"])
                else:
                    sku = v["sku"] or _auto_sku(db, slug, v["size"], v["color"], taken)
                    cur = db.execute(
                        "INSERT INTO product_variants(product_id, sku, size, color, color_hex, stock, low_stock_threshold, is_active)"
                        " VALUES(?,?,?,?,?,0,?,?)", (product_id, sku, v["size"], v["color"], v["color_hex"], v["low"], v["active"]))
                    if v["stock"]:
                        inventory.adjust(db, cur.lastrowid, v["stock"], "initial", "Initial stock", user_id)
            for vid in set(existing) - kept:
                used = db.execute("SELECT 1 FROM order_items WHERE variant_id=? LIMIT 1", (vid,)).fetchone()
                if used:  # keep the row for history/reporting, just stop selling it
                    db.execute("UPDATE product_variants SET is_active=0 WHERE id=?", (vid,))
                else:
                    db.execute("DELETE FROM product_variants WHERE id=?", (vid,))

            # images: delete flagged, update alt/position, append new
            delete_ids = {to_int(x) for x in form.getlist("img_delete")}
            for iid, alt, pos in zip(form.getlist("img_id"), form.getlist("img_alt"), form.getlist("img_pos")):
                iid = to_int(iid)
                row = db.execute("SELECT * FROM product_images WHERE id=? AND product_id=?", (iid, product_id)).fetchone()
                if not row:
                    continue
                if iid in delete_ids:
                    db.execute("DELETE FROM product_images WHERE id=?", (iid,))
                    removed_files.append(row["filename"])
                else:
                    db.execute("UPDATE product_images SET alt=?, position=? WHERE id=?",
                               (clean(alt, 200), to_int(pos, 0, 0, 999), iid))
            nxt = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM product_images WHERE product_id=?", (product_id,)).fetchone()[0]
            for i, fn in enumerate(new_files):
                db.execute("INSERT INTO product_images(product_id, filename, alt, position) VALUES(?,?,?,?)",
                           (product_id, fn, name, nxt + i))
    except sqlite3.IntegrityError as e:
        for n in new_files:
            media.delete_file(upload_dir, n)
        msg = "That SKU is already used by another variant." if "sku" in str(e).lower() else "Could not save: " + str(e)
        return product_id, [msg]
    except Exception:
        for n in new_files:
            media.delete_file(upload_dir, n)
        raise

    for fn in removed_files:
        if not _file_in_use(db, fn):
            media.delete_file(upload_dir, fn)
    return product_id, []


def _file_in_use(db, filename):
    return bool(db.execute(
        "SELECT 1 FROM product_images WHERE filename=? UNION SELECT 1 FROM order_items WHERE image=? LIMIT 1",
        (filename, filename)).fetchone())


def delete_product(db, upload_dir, product_id):
    """Hard delete. Order items keep their snapshots (product/variant FKs become NULL)."""
    files = [r["filename"] for r in db.execute("SELECT filename FROM product_images WHERE product_id=?", (product_id,))]
    with transaction(db):
        db.execute("DELETE FROM products WHERE id=?", (product_id,))
    for fn in files:
        if not _file_in_use(db, fn):
            media.delete_file(upload_dir, fn)
