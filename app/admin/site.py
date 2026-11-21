"""Store configuration: settings, shipping methods, homepage content, policy pages."""
import re

from flask import current_app, flash, g, redirect, render_template, request, url_for

from ..db import get_db, transaction
from ..payments import get_provider
from ..security import staff_required
from ..services import media
from ..services import settings as settings_svc
from ..util import clean, clean_multiline, parse_money, slugify, to_int
from . import bp

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _upload(field, files=None):
    """Save an uploaded image field; returns filename, None (nothing uploaded). Raises UploadError."""
    fs = (files or request.files).get(field)
    if fs and fs.filename:
        return media.save_image(fs, current_app.config["UPLOAD_DIR"], current_app.config["MAX_IMAGE_BYTES"])
    return None


def _safe_url(value):
    """Allow site-relative paths or http(s) URLs only (blocks javascript: etc.)."""
    v = clean(value, 300)
    return v if (v.startswith("/") and not v.startswith("//")) or v.startswith(("http://", "https://")) else ""


# ---- settings ---------------------------------------------------------------------------------
@bp.route("/settings", methods=["GET", "POST"])
@staff_required("*")
def settings():
    db = get_db()
    s = settings_svc.load(db)
    if request.method == "POST":
        f, errors, new = request.form, [], {}
        new["store_name"] = clean(f.get("store_name"), 60) or s["store_name"]
        new["store_tagline"] = clean(f.get("store_tagline"), 120)
        new["meta_description"] = clean(f.get("meta_description"), 300)
        new["footer_text"] = clean(f.get("footer_text"), 300)
        for key in ("color_ink", "color_paper", "color_accent", "color_muted"):
            v = clean(f.get(key), 7)
            if HEX.match(v):
                new[key] = v.lower()
            else:
                errors.append(f"{key.replace('color_', '').title()} colour must look like #1a2b3c.")
        new["contact_email"] = clean(f.get("contact_email"), 254)
        new["contact_phone"] = clean(f.get("contact_phone"), 40)
        new["store_address"] = clean(f.get("store_address"), 200)
        for key in ("social_instagram", "social_facebook", "social_tiktok", "social_pinterest"):
            new[key] = _safe_url(f.get(key))
        cur = clean(f.get("currency"), 3).upper()
        if len(cur) == 3 and cur.isalpha():
            new["currency"] = cur
            new["currency_symbol"] = clean(f.get("currency_symbol"), 4) or settings_svc.CURRENCY_SYMBOLS.get(cur, cur + " ")
        else:
            errors.append("Currency must be a 3-letter code such as EUR or USD.")
        new["tax_enabled"] = bool(f.get("tax_enabled"))
        try:
            rate = float(f.get("tax_rate") or 0)
            if not 0 <= rate <= 60:
                raise ValueError
            new["tax_rate"] = rate
        except ValueError:
            errors.append("Tax rate must be between 0 and 60.")
        new["tax_inclusive"] = f.get("tax_mode") != "exclusive"
        new["order_prefix"] = re.sub(r"[^A-Z0-9]", "", clean(f.get("order_prefix"), 6).upper()) or "ORD"
        exp = to_int(f.get("pending_order_expiry_minutes"), None, 5, 10080)
        if exp is None:
            errors.append("Unpaid-order expiry must be between 5 and 10080 minutes.")
        else:
            new["pending_order_expiry_minutes"] = exp
        new["shipping_countries"] = [clean(x, 80) for x in (f.get("shipping_countries") or "").splitlines() if clean(x, 80)][:250]
        new["default_country"] = clean(f.get("default_country"), 80)

        methods, codes = [], f.getlist("pm_code")
        enabled = set(f.getlist("pm_enabled"))
        for i, code in enumerate(codes):
            old = next((m for m in s["payment_methods"] if m["code"] == code), None)
            if old is None or get_provider(old["provider"]) is None:
                continue
            label = clean((f.getlist("pm_label") + [""] * len(codes))[i], 60) or old["label"]
            desc = clean((f.getlist("pm_desc") + [""] * len(codes))[i], 160)
            methods.append(dict(old, label=label, description=desc, enabled=code in enabled))
        if not any(m["enabled"] for m in methods):
            errors.append("Keep at least one payment method enabled.")
        else:
            new["payment_methods"] = methods

        try:
            logo = _upload("logo")
            if logo:
                new["logo_image"] = logo
            elif f.get("remove_logo"):
                new["logo_image"] = ""
        except media.UploadError as e:
            errors.append(f"Logo: {e}")

        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("admin.settings"))
        with transaction(db):
            settings_svc.save_many(db, new)
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", cfg=s, providers={m["provider"]: get_provider(m["provider"]) for m in s["payment_methods"]})


# ---- shipping ---------------------------------------------------------------------------------
@bp.route("/shipping", methods=["GET", "POST"])
@staff_required("*")
def shipping():
    db = get_db()
    if request.method == "POST":
        f, action, mid = request.form, request.form.get("action"), to_int(request.form.get("id"))
        if action == "delete" and mid:
            if db.execute("SELECT COUNT(*) FROM shipping_methods WHERE is_active=1 AND id != ?", (mid,)).fetchone()[0] == 0:
                flash("Keep at least one active delivery method.", "error")
            else:
                db.execute("DELETE FROM shipping_methods WHERE id=?", (mid,))  # past orders keep the method name
                flash("Delivery method deleted.", "info")
        else:
            name = clean(f.get("name"), 80)
            price = parse_money(f.get("price") or "0")
            free_raw = (f.get("free_over") or "").strip()
            free = parse_money(free_raw) if free_raw else None
            active = 1 if f.get("is_active") else 0
            if not name or price is None or (free_raw and free is None):
                flash("Enter a name and valid amounts.", "error")
            elif mid and not active and db.execute(
                    "SELECT COUNT(*) FROM shipping_methods WHERE is_active=1 AND id != ?", (mid,)).fetchone()[0] == 0:
                flash("Keep at least one active delivery method.", "error")
            else:
                vals = (name, clean(f.get("description"), 160), price, free, to_int(f.get("sort_order"), 0, -1000, 1000), active)
                if mid and db.execute("SELECT 1 FROM shipping_methods WHERE id=?", (mid,)).fetchone():
                    db.execute("UPDATE shipping_methods SET name=?, description=?, price_cents=?, free_over_cents=?, sort_order=?, is_active=? WHERE id=?",
                               vals + (mid,))
                else:
                    db.execute("INSERT INTO shipping_methods(name, description, price_cents, free_over_cents, sort_order, is_active) VALUES(?,?,?,?,?,?)", vals)
                flash("Delivery method saved.", "success")
        return redirect(url_for("admin.shipping"))
    return render_template("admin/shipping.html", rows=db.execute("SELECT * FROM shipping_methods ORDER BY sort_order, id").fetchall())


# ---- homepage content -------------------------------------------------------------------------
PROMO_SLOTS = 2
SECTION_TOGGLES = ["show_collections", "show_new_arrivals", "show_best_sellers", "show_promos",
                   "show_brand_intro", "show_instagram", "show_newsletter"]


@bp.route("/content", methods=["GET", "POST"])
@staff_required("content")
def content():
    db = get_db()
    s = settings_svc.load(db)
    if request.method == "POST":
        f, new, errors = request.form, {}, []
        new["announcement_enabled"] = bool(f.get("announcement_enabled"))
        new["announcement_text"] = clean(f.get("announcement_text"), 160)
        new["announcement_link"] = _safe_url(f.get("announcement_link"))
        for k, n in [("hero_eyebrow", 60), ("hero_title", 120), ("hero_subtitle", 240), ("hero_cta_label", 30),
                     ("brand_intro_title", 120), ("instagram_title", 80), ("instagram_handle", 60),
                     ("newsletter_title", 80), ("newsletter_text", 240)]:
            new[k] = clean(f.get(k), n)
        new["hero_cta_url"] = _safe_url(f.get("hero_cta_url")) or "/shop"
        new["brand_intro_text"] = clean_multiline(f.get("brand_intro_text"), 1500)
        for k in SECTION_TOGGLES:
            new[k] = bool(f.get(k))

        banners = []
        old = s.get("promo_banners") or []
        for i in range(PROMO_SLOTS):
            prev = old[i] if i < len(old) else {}
            b = dict(title=clean(f.get(f"promo{i}_title"), 80), text=clean(f.get(f"promo{i}_text"), 200),
                     cta_label=clean(f.get(f"promo{i}_cta_label"), 30), cta_url=_safe_url(f.get(f"promo{i}_cta_url")),
                     enabled=bool(f.get(f"promo{i}_enabled")), image=prev.get("image", ""))
            try:
                up = _upload(f"promo{i}_image")
                if up:
                    b["image"] = up
            except media.UploadError as e:
                errors.append(f"Promo {i + 1} image: {e}")
            banners.append(b)
        new["promo_banners"] = banners

        for field, key in [("hero_image", "hero_image"), ("brand_intro_image", "brand_intro_image")]:
            try:
                up = _upload(field)
                if up:
                    new[key] = up
            except media.UploadError as e:
                errors.append(f"{field.replace('_', ' ').title()}: {e}")

        gallery = [x for x in s.get("instagram_images", []) if x not in set(f.getlist("ig_delete"))]
        for fs in request.files.getlist("ig_new"):
            if fs and fs.filename and len(gallery) < 8:
                try:
                    gallery.append(media.save_image(fs, current_app.config["UPLOAD_DIR"], current_app.config["MAX_IMAGE_BYTES"]))
                except media.UploadError as e:
                    errors.append(f"Gallery: {e}")
        new["instagram_images"] = gallery

        with transaction(db):
            settings_svc.save_many(db, new)
        for e in errors:
            flash(e, "error")
        flash("Homepage content saved.", "success")
        return redirect(url_for("admin.content"))
    banners = list(s.get("promo_banners") or [])
    while len(banners) < PROMO_SLOTS:
        banners.append(dict(title="", text="", cta_label="", cta_url="", enabled=False, image=""))
    return render_template("admin/content.html", cfg=s, banners=banners)


# ---- policy / info pages ----------------------------------------------------------------------
@bp.route("/pages", methods=["GET", "POST"])
@staff_required("content")
def pages():
    db = get_db()
    if request.method == "POST":
        f, action = request.form, request.form.get("action")
        slug = slugify(clean(f.get("slug"), 60) or clean(f.get("title"), 60))
        if action == "delete":
            db.execute("DELETE FROM pages WHERE slug=?", (clean(f.get("slug"), 60),))
            flash("Page deleted.", "info")
        else:
            title = clean(f.get("title"), 120)
            if not title:
                flash("A title is required.", "error")
                return redirect(url_for("admin.pages"))
            original = clean(f.get("original_slug"), 60)
            vals = (title, clean_multiline(f.get("body"), 20000), 1 if f.get("show_in_footer") else 0,
                    to_int(f.get("sort_order"), 0, -1000, 1000))
            if original and db.execute("SELECT 1 FROM pages WHERE slug=?", (original,)).fetchone():
                db.execute("UPDATE pages SET title=?, body=?, show_in_footer=?, sort_order=?, updated_at=datetime('now') WHERE slug=?",
                           vals + (original,))
                slug = original
            elif db.execute("SELECT 1 FROM pages WHERE slug=?", (slug,)).fetchone():
                flash("A page with that address already exists.", "error")
                return redirect(url_for("admin.pages"))
            else:
                db.execute("INSERT INTO pages(slug, title, body, show_in_footer, sort_order) VALUES(?,?,?,?,?)", (slug,) + vals)
            flash("Page saved.", "success")
            return redirect(url_for("admin.pages", edit=slug))
        return redirect(url_for("admin.pages"))
    rows = db.execute("SELECT * FROM pages ORDER BY sort_order, title").fetchall()
    edit = request.args.get("edit")
    current = next((r for r in rows if r["slug"] == edit), None)
    return render_template("admin/pages.html", rows=rows, current=current)
