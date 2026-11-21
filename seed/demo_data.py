"""Fictional demo content for the temporary "ATELIER" brand.

Everything here is data written into the database by seed/run.py. Replace the brand, products and
copy through the admin dashboard (or swap this file) — application code never references them.
"""

BRAND_SETTINGS = {
    "store_name": "ATELIER",
    "store_tagline": "Considered clothing, made to last",
    "meta_description": "ATELIER — a demo store for premium contemporary fashion.",
    "footer_text": "Demonstration store. All products, prices and people are fictional.",
    "color_ink": "#1b1a18",
    "color_paper": "#f7f4ef",
    "color_accent": "#9a7b5a",
    "color_muted": "#6d675e",
    "contact_email": "hello@atelier.example",
    "contact_phone": "+383 38 000 000",
    "store_address": "Rr. Demo 12, 10000 Prishtinë",
    "social_instagram": "https://instagram.com/",
    "social_facebook": "https://facebook.com/",
    "social_tiktok": "https://tiktok.com/",
    "social_pinterest": "https://pinterest.com/",
    "currency": "EUR",
    "currency_symbol": "€",
    "tax_enabled": True,
    "tax_rate": 18,
    "tax_inclusive": True,
    "order_prefix": "ATL",
    "pending_order_expiry_minutes": 120,
    "shipping_countries": ["Kosovo", "Albania", "North Macedonia", "Montenegro", "Germany", "Switzerland", "Italy", "Austria"],
    "default_country": "Kosovo",
    "announcement_enabled": True,
    "announcement_text": "Complimentary standard shipping on orders over €100 — use code WELCOME10 for 10% off your first order",
    "announcement_link": "/shop",
    "hero_eyebrow": "Autumn / Winter",
    "hero_title": "Quiet clothes for loud days",
    "hero_subtitle": "Timeless silhouettes in natural fibres, cut to move with you and built to be worn for years.",
    "hero_cta_label": "Shop the collection",
    "hero_cta_url": "/shop",
    "brand_intro_title": "Made slowly, worn often",
    "brand_intro_text": (
        "ATELIER began with a simple idea: fewer, better things. Every piece is designed in small runs, "
        "cut from certified natural fibres and finished by hand in family-run workshops.\n\n"
        "We design for the long term — pieces that layer, repeat and age well — so you can build a wardrobe "
        "you actually love rather than one you outgrow."),
    "instagram_title": "Worn by you",
    "instagram_handle": "@atelier.demo",
    "newsletter_title": "Join the list",
    "newsletter_text": "New arrivals, studio notes and early access to sales — once a month, never more.",
}

PROMOS = [
    dict(title="The Evening Edit", text="Silk, satin and sculpted lines for the long nights ahead.",
         cta_label="Explore evening", cta_url="/shop?collection=evening", enabled=True),
    dict(title="Finishing touches", text="Leather totes and wool scarves that complete every outfit.",
         cta_label="Shop accessories", cta_url="/shop?category=accessories", enabled=True),
]

CATEGORIES = [
    ("Outerwear", "Coats, trenches and jackets for every season."),
    ("Knitwear", "Merino, cashmere and cotton knits."),
    ("Dresses", "From slip dresses to shirt dresses."),
    ("Tops", "Shirts, tees and tanks."),
    ("Trousers", "Tailored and relaxed fits."),
    ("Accessories", "Bags, scarves and finishing touches."),
]

COLLECTIONS = [
    # name, description, featured
    ("The Autumn Edit", "Warm textures and earthy tones for the colder months.", True),
    ("Quiet Neutrals", "Oatmeal, stone and camel — the foundation of a calm wardrobe.", True),
    ("Studio Essentials", "Everyday pieces we reach for again and again.", True),
    ("Evening", "Elevated pieces for after dark.", False),
]

SIZES = ["XS", "S", "M", "L", "XL"]

# slug-less spec; `kind`/`opts` drive the generated placeholder imagery
PRODUCTS = [
    dict(name="Wool Overcoat", category="Outerwear", price=289, sale=None, featured=True, kind="coat", opts={"belt": False},
         colors=[("Camel", "#b08d63"), ("Charcoal", "#3b3b3d")], sizes=SIZES, collections=["The Autumn Edit", "Quiet Neutrals"],
         description="A long, softly structured overcoat in a dense Italian wool blend. Notched lapels, a clean front and deep pockets make it an effortless layer over knits and tailoring.",
         details="80% virgin wool, 20% polyamide. Fully lined in viscose. Dry clean only."),
    dict(name="Belted Trench", category="Outerwear", price=249, sale=199, featured=True, kind="coat", opts={"belt": True},
         colors=[("Sand", "#cdb99a"), ("Black", "#1c1c1c")], sizes=SIZES, collections=["The Autumn Edit"],
         description="Our take on the classic trench in water-repellent cotton gabardine, with a tie belt that cinches the waist and a relaxed shoulder.",
         details="100% organic cotton gabardine, water-repellent finish. Cold machine wash or dry clean."),
    dict(name="Quilted Liner Jacket", category="Outerwear", price=179, sale=None, featured=False, kind="coat", opts={"belt": False, "len": 760},
         colors=[("Olive", "#6b6b4a")], sizes=SIZES, collections=["Studio Essentials"],
         description="A light, quilted jacket that works alone in mild weather or under a coat when it turns cold.",
         details="Recycled polyester shell and fill. Machine wash at 30°C."),
    dict(name="Merino Crew Sweater", category="Knitwear", price=109, sale=None, featured=True, kind="sweater", opts={"neck": "crew"},
         colors=[("Oatmeal", "#d8cbb4"), ("Forest", "#3f5240"), ("Ink", "#26303d")], sizes=SIZES,
         collections=["Quiet Neutrals", "Studio Essentials"],
         description="Our everyday sweater, knitted from extra-fine merino that is soft against the skin, breathable and naturally temperature-regulating.",
         details="100% extra-fine merino wool (RWS certified). Hand wash cold or wool cycle."),
    dict(name="Chunky Cable Cardigan", category="Knitwear", price=139, sale=109, featured=False, kind="sweater", opts={"neck": "crew", "open": True},
         colors=[("Cream", "#eee6d6"), ("Mocha", "#6a4e3d")], sizes=SIZES, collections=["The Autumn Edit"],
         description="A generous cardigan in a heavyweight cable knit with horn-effect buttons. Made to be lived in.",
         details="60% lambswool, 40% cotton. Hand wash cold, dry flat."),
    dict(name="Cashmere Turtleneck", category="Knitwear", price=189, sale=None, featured=True, kind="sweater", opts={"neck": "turtle"},
         colors=[("Stone", "#b9b2a6"), ("Black", "#1c1c1c")], sizes=SIZES, collections=["Quiet Neutrals"], sold_out=True,
         description="Luxuriously light Grade-A cashmere in a fine gauge. A turtleneck that layers beautifully and feels like a hug.",
         details="100% Grade-A cashmere. Hand wash cold with cashmere shampoo."),
    dict(name="Silk Slip Dress", category="Dresses", price=159, sale=None, featured=True, kind="dress", opts={"straps": True},
         colors=[("Champagne", "#d9c2a3"), ("Midnight", "#1f2a44")], sizes=SIZES, collections=["Evening"],
         description="A bias-cut slip dress in washed silk satin with adjustable straps and a fluid, floor-skimming drape.",
         details="100% mulberry silk. Dry clean recommended."),
    dict(name="Pleated Midi Dress", category="Dresses", price=139, sale=None, featured=False, kind="dress", opts={"straps": False},
         colors=[("Terracotta", "#b4694a")], sizes=SIZES, collections=["The Autumn Edit", "Evening"],
         description="Knife pleats, a nipped waist and short sleeves — a dress with movement that goes from desk to dinner.",
         details="100% recycled polyester crêpe. Machine wash at 30°C, line dry."),
    dict(name="Linen Shirt Dress", category="Dresses", price=129, sale=None, featured=False, kind="dress", opts={"straps": False},
         colors=[("Chalk", "#ece7dc"), ("Sage", "#9aa68a")], sizes=SIZES, collections=["Studio Essentials"],
         description="A relaxed shirt dress in stonewashed European linen that softens with every wear.",
         details="100% European flax linen. Machine wash at 30°C."),
    dict(name="Poplin Shirt", category="Tops", price=79, sale=None, featured=False, kind="shirt", opts={"collar": True, "long": True},
         colors=[("White", "#f4f2ee"), ("Sky", "#b8cde0")], sizes=SIZES, collections=["Studio Essentials"],
         description="A crisp, slightly oversized shirt in organic cotton poplin with mother-of-pearl buttons.",
         details="100% organic cotton poplin. Machine wash at 40°C."),
    dict(name="Ribbed Tank", category="Tops", price=39, sale=None, featured=False, kind="shirt", opts={"collar": False, "long": False},
         colors=[("Black", "#1c1c1c"), ("Ecru", "#e4dac6")], sizes=SIZES, collections=["Studio Essentials"],
         description="A fitted, stretchy rib tank that layers under everything. Buy two.",
         details="95% organic cotton, 5% elastane. Machine wash at 30°C."),
    dict(name="Organic Cotton Tee", category="Tops", price=45, sale=None, featured=False, kind="shirt", opts={"collar": False, "long": False},
         colors=[("Chalk", "#ece7dc"), ("Ink", "#26303d"), ("Terracotta", "#b4694a")], sizes=SIZES, collections=["Studio Essentials"],
         description="A heavyweight tee with a boxy fit and a clean neckline. Garment-dyed for a lived-in softness.",
         details="100% organic cotton, 220gsm. Machine wash at 30°C."),
    dict(name="Wide-Leg Wool Trousers", category="Trousers", price=119, sale=None, featured=True, kind="pants", opts={"wide": True},
         colors=[("Charcoal", "#3b3b3d"), ("Camel", "#b08d63")], sizes=SIZES, collections=["Quiet Neutrals", "The Autumn Edit"],
         description="High-rise trousers with a generous, fluid leg and sharp pressed creases in a mid-weight wool.",
         details="70% wool, 30% recycled polyester. Dry clean or cold hand wash."),
    dict(name="Tailored Straight Trousers", category="Trousers", price=109, sale=89, featured=False, kind="pants", opts={"wide": False},
         colors=[("Navy", "#232f4b"), ("Ecru", "#e4dac6")], sizes=SIZES, collections=["Studio Essentials"],
         description="A clean straight leg with a flat front and discreet side pockets. The trouser that goes with everything.",
         details="Stretch cotton twill. Machine wash at 30°C."),
    dict(name="Leather Tote", category="Accessories", price=229, sale=None, featured=True, kind="bag", opts={},
         colors=[("Tan", "#a5703d"), ("Black", "#1c1c1c")], sizes=["One Size"], collections=["The Autumn Edit", "Quiet Neutrals"],
         description="A structured everyday tote in vegetable-tanned leather that develops a rich patina over time. Fits a 13\" laptop.",
         details="Vegetable-tanned Italian leather, cotton lining. Wipe clean; condition occasionally."),
    dict(name="Wool Scarf", category="Accessories", price=69, sale=None, featured=False, kind="scarf", opts={},
         colors=[("Camel", "#b08d63"), ("Grey", "#9a9a98")], sizes=["One Size"], collections=["The Autumn Edit"],
         description="An oversized, brushed wool scarf with hand-finished fringe. Wrap, drape or knot.",
         details="100% brushed wool. Hand wash cold."),
    dict(name="Velvet Blazer", category="Outerwear", price=199, sale=None, featured=False, kind="coat", opts={"len": 820},
         colors=[("Midnight", "#1f2a44")], sizes=SIZES, collections=["Evening"], draft=True,
         description="Draft product: a velvet evening blazer. Unpublished to demonstrate draft products.",
         details="Cotton velvet."),
]

SHIPPING = [
    dict(name="Standard delivery", description="3–5 business days", price=3.90, free_over=100.0, sort_order=1),
    dict(name="Express delivery", description="1–2 business days", price=9.90, free_over=None, sort_order=2),
    dict(name="Store pickup", description="Collect from our Prishtinë studio — ready in 24h", price=0.0, free_over=None, sort_order=3),
]

DISCOUNTS = [
    dict(code="WELCOME10", kind="percent", value=10, min_subtotal=0),
    dict(code="SAVE15", kind="fixed", value=15.0, min_subtotal=80.0),
    dict(code="VIP20", kind="percent", value=20, min_subtotal=150.0, max_uses=50),
]

PAGES = [
    ("about", "About ATELIER", "ATELIER is a fictional brand used to demonstrate this store.\n\nReplace this text from Admin → Pages.", 1, 1),
    ("shipping", "Shipping & delivery",
     "We ship to Kosovo, Albania, North Macedonia, Montenegro, Germany, Switzerland, Italy and Austria.\n\nStandard delivery takes 3–5 business days and is free on orders over €100. Express delivery takes 1–2 business days.\n\nThis is demonstration content — edit it in Admin → Pages.", 1, 2),
    ("returns", "Returns & exchanges",
     "You have 30 days from delivery to return unworn items in their original condition.\n\nContact us with your order number and we will arrange a free return label.\n\nThis is demonstration content — edit it in Admin → Pages.", 1, 3),
    ("size-guide", "Size guide",
     "XS: EU 34 / UK 6\nS: EU 36 / UK 8\nM: EU 38 / UK 10\nL: EU 40 / UK 12\nXL: EU 42 / UK 14\n\nIf you are between sizes, we recommend sizing up for a relaxed fit.", 1, 4),
    ("privacy", "Privacy policy",
     "Placeholder privacy policy. Before launch, replace this with a policy reviewed for your jurisdiction (GDPR and local law).", 1, 5),
    ("terms", "Terms & conditions",
     "Placeholder terms and conditions. Before launch, replace these with terms reviewed by a qualified professional.", 1, 6),
]

DEMO_CUSTOMERS = [
    # first, last, email, phone, city, country
    ("Elira", "Krasniqi", "customer@example.com", "+383 44 111 222", "Prishtinë", "Kosovo"),
    ("Arben", "Hoxha", "arben.hoxha@example.com", "+355 69 222 3333", "Tiranë", "Albania"),
    ("Mira", "Jovanović", "mira.j@example.com", "+389 70 333 444", "Skopje", "North Macedonia"),
    ("Lea", "Berisha", "lea.berisha@example.com", "+383 45 555 666", "Prizren", "Kosovo"),
    ("Daniel", "Weber", "daniel.weber@example.com", "+49 151 2345 6789", "Munich", "Germany"),
]

# customer index (None = guest), items [(product, colour, size, qty)], days ago, payment code, discount, status path
DEMO_ORDERS = [
    (0, [("Wool Overcoat", "Camel", "M", 1), ("Wool Scarf", "Camel", "One Size", 1)], 27, "card_demo", "", ["processing", "shipped", "delivered"]),
    (1, [("Merino Crew Sweater", "Forest", "L", 2)], 25, "card_demo", "WELCOME10", ["processing", "shipped", "delivered"]),
    (None, [("Silk Slip Dress", "Midnight", "S", 1)], 23, "card_demo", "", ["processing", "shipped", "delivered"]),
    (2, [("Wide-Leg Wool Trousers", "Charcoal", "M", 1), ("Poplin Shirt", "White", "M", 1)], 20, "cod", "", ["processing", "shipped", "delivered"]),
    (3, [("Leather Tote", "Tan", "One Size", 1)], 18, "card_demo", "", ["processing", "shipped", "delivered"]),
    (0, [("Chunky Cable Cardigan", "Cream", "S", 1)], 15, "card_demo", "", ["processing", "shipped", "delivered", "refunded"]),
    (4, [("Belted Trench", "Sand", "L", 1), ("Organic Cotton Tee", "Chalk", "L", 2)], 13, "card_demo", "SAVE15", ["processing", "shipped", "delivered"]),
    (None, [("Merino Crew Sweater", "Oatmeal", "M", 1)], 11, "cod", "", ["processing", "shipped"]),
    (1, [("Pleated Midi Dress", "Terracotta", "M", 1)], 9, "card_demo", "", ["processing", "shipped"]),
    (3, [("Tailored Straight Trousers", "Navy", "S", 1), ("Ribbed Tank", "Black", "S", 2)], 7, "card_demo", "", ["processing"]),
    (2, [("Wool Overcoat", "Charcoal", "L", 1)], 5, "card_demo", "VIP20", []),
    (0, [("Linen Shirt Dress", "Sage", "M", 1)], 3, "cod", "", []),
    (None, [("Organic Cotton Tee", "Ink", "M", 1)], 2, "card_demo", "", ["cancelled"]),
    (4, [("Merino Crew Sweater", "Ink", "XL", 1), ("Wool Scarf", "Grey", "One Size", 1)], 1, "card_demo", "", []),
]
