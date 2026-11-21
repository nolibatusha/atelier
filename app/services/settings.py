"""Store settings: persisted as JSON in the `settings` table.

DEFAULTS are neutral, brand-free fallbacks. The fictional demo brand lives in seed/demo_data.py
and is written to the database by the seeder, never baked into application code.
"""
import json

CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "ALL": "L", "PLN": "zł", "CAD": "$", "AUD": "$"}

DEFAULTS = {
    # identity & branding
    "store_name": "My Store",
    "store_tagline": "",
    "logo_image": "",
    "color_ink": "#1c1b19",
    "color_paper": "#faf8f5",
    "color_accent": "#8a6f4d",
    "color_muted": "#6f6a62",
    "meta_description": "",
    "footer_text": "",
    # contact
    "contact_email": "",
    "contact_phone": "",
    "store_address": "",
    "social_instagram": "",
    "social_facebook": "",
    "social_tiktok": "",
    "social_pinterest": "",
    # money
    "currency": "EUR",
    "currency_symbol": "€",
    "tax_enabled": False,
    "tax_rate": 0,
    "tax_inclusive": True,
    "order_prefix": "ORD",
    "pending_order_expiry_minutes": 120,
    "shipping_countries": [],
    "default_country": "",
    "payment_methods": [
        {"code": "card_demo", "label": "Card (simulated)", "provider": "simulated", "enabled": True,
         "description": "Demo payment — no real money is charged."},
        {"code": "cod", "label": "Cash on delivery", "provider": "cod", "enabled": True,
         "description": "Pay when your order arrives."},
    ],
    # homepage content
    "announcement_enabled": False,
    "announcement_text": "",
    "announcement_link": "",
    "hero_eyebrow": "",
    "hero_title": "Welcome",
    "hero_subtitle": "",
    "hero_cta_label": "Shop now",
    "hero_cta_url": "/shop",
    "hero_image": "",
    "promo_banners": [],
    "brand_intro_title": "",
    "brand_intro_text": "",
    "brand_intro_image": "",
    "instagram_title": "",
    "instagram_handle": "",
    "instagram_images": [],
    "newsletter_title": "Stay in the loop",
    "newsletter_text": "",
    "show_collections": True,
    "show_new_arrivals": True,
    "show_best_sellers": True,
    "show_promos": True,
    "show_brand_intro": True,
    "show_instagram": True,
    "show_newsletter": True,
}


def load(db):
    out = dict(DEFAULTS)
    for row in db.execute("SELECT key, value FROM settings"):
        try:
            out[row["key"]] = json.loads(row["value"])
        except ValueError:
            pass
    return out


def current():
    """Settings for the current request (loaded once, cached on flask.g)."""
    from flask import g

    from ..db import get_db

    if "settings" not in g:
        g.settings = load(get_db())
    return g.settings


def save(db, key, value):
    db.execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, json.dumps(value)),
    )


def save_many(db, values):
    for k, v in values.items():
        save(db, k, v)
