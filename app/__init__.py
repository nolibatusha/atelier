"""Application factory."""
import mimetypes
from datetime import datetime
from pathlib import Path

from flask import Flask, g, render_template, request, url_for
from markupsafe import Markup, escape
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db as dbm
from . import security
from .config import build_config
from .services import settings as settings_svc


def _fix_mimetypes():
    """Windows reads MIME types from the registry, which often maps .js/.css to text/plain.
    With `X-Content-Type-Options: nosniff` browsers then refuse to load the styles and scripts,
    so pin the correct types (init first so the registry can't override them afterwards)."""
    mimetypes.init()
    for mime, ext in (("text/css", ".css"), ("text/javascript", ".js"), ("image/svg+xml", ".svg"),
                      ("image/webp", ".webp"), ("image/png", ".png"), ("image/jpeg", ".jpg"),
                      ("image/jpeg", ".jpeg"), ("application/json", ".json")):
        mimetypes.add_type(mime, ext)


def create_app(overrides=None):
    _fix_mimetypes()
    cfg = build_config(overrides)
    app = Flask(__name__)
    app.config.update(cfg)
    Path(cfg["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    if cfg.get("TRUSTED_PROXIES"):
        n = cfg["TRUSTED_PROXIES"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    dbm.init_app(app)

    # ---- request lifecycle ----
    @app.before_request
    def _before():
        if request.endpoint == "static":
            return
        security.csrf_protect()
        security.load_user()

    app.after_request(security.add_security_headers)

    # ---- templating ----
    get_settings = settings_svc.current

    @app.context_processor
    def _ctx():
        from .blueprints.cart import current_cart_count

        db = dbm.get_db()
        s = get_settings()
        return {
            "s": s,
            "can": lambda perm: security.has_perm(g.get("user"), perm),
            "current_user": g.get("user"),
            "current_customer": g.get("customer"),
            "cart_count": current_cart_count(),
            "nav_categories": db.execute(
                "SELECT slug, name FROM categories WHERE is_active=1 ORDER BY sort_order, name").fetchall(),
            "footer_pages": db.execute(
                "SELECT slug, title FROM pages WHERE show_in_footer=1 ORDER BY sort_order, title").fetchall(),
        }

    app.add_template_global(security.csrf_token, "csrf_token")

    static_dir = Path(app.static_folder)

    @app.template_global("asset")
    def asset(path):
        """Static URL with a version stamp, so browsers never keep an old stylesheet/script after an update."""
        try:
            v = int((static_dir / path).stat().st_mtime)
        except OSError:
            v = 0
        return url_for("static", filename=path, v=v)

    @app.template_global("page_url")
    def page_url(n):
        args = request.args.to_dict(flat=False)
        args["page"] = [str(n)]
        return url_for(request.endpoint, **{**(request.view_args or {}), **{k: (v if len(v) > 1 else v[0]) for k, v in args.items()}})

    @app.template_filter("money")
    def money(cents):
        s = get_settings()
        sym = s.get("currency_symbol") or s.get("currency", "")
        return f"{sym}{(cents or 0) / 100:,.2f}"

    @app.template_filter("img")
    def img(filename):
        return url_for("shop.media", filename=filename) if filename else url_for("static", filename="img/placeholder.svg")

    def _media_url(filename, width=None):
        return url_for("shop.media", filename=filename, w=width) if width else url_for("shop.media", filename=filename)

    @app.template_global("img_attrs")
    def img_attrs(filename, sizes="100vw", widths=(320, 480, 720, 1080), default=None):
        """src + srcset + sizes for an uploaded image, so phones download small files instead of 2000px originals."""
        if not filename:
            return Markup(f'src="{escape(url_for("static", filename="img/placeholder.svg"))}"')
        from .services.media import srcset
        default = default or widths[min(1, len(widths) - 1)]
        return Markup('src="%s" srcset="%s" sizes="%s"' % (
            escape(_media_url(filename, default)), escape(srcset(_media_url, filename, widths)), escape(sizes)))

    @app.template_global("img_srcset")
    def img_srcset(filename, widths=(320, 480, 720, 1080)):
        from .services.media import srcset
        return srcset(_media_url, filename, widths) if filename else ""

    @app.template_filter("imgw")
    def imgw(filename, width):
        return _media_url(filename, width) if filename else url_for("static", filename="img/placeholder.svg")

    @app.template_filter("dt")
    def fmt_dt(value, fmt="%d %b %Y, %H:%M"):
        try:
            return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").strftime(fmt) + (" UTC" if "%H" in fmt else "")
        except (TypeError, ValueError):
            return value or ""

    @app.template_filter("paragraphs")
    def paragraphs(text):
        """Plain text -> escaped <p> blocks. Admin-written content never becomes raw HTML."""
        blocks = [b.strip() for b in (text or "").replace("\r", "").split("\n\n") if b.strip()]
        return Markup("".join(f"<p>{escape(b).replace(chr(10), Markup('<br>'))}</p>" for b in blocks))

    @app.template_filter("status_label")
    def status_label(value):
        return (value or "").replace("_", " ").title()

    # ---- blueprints ----
    from .admin import bp as admin_bp
    from .blueprints.account import bp as account_bp
    from .blueprints.cart import bp as cart_bp
    from .blueprints.shop import bp as shop_bp

    app.register_blueprint(shop_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(admin_bp)

    # ---- errors ----
    def _err(code, title, msg):
        def handler(e):
            m = getattr(e, "description", None) or msg
            return render_template("error.html", code=code, title=title, message=m), code
        return handler

    for code, title, msg in [
        (400, "Request problem", "Something about that request wasn't right."),
        (403, "Access denied", "You don't have permission to view this page."),
        (404, "Page not found", "We couldn't find the page you were looking for."),
        (413, "File too large", "The upload was too large."),
        (429, "Slow down", "Too many attempts. Please wait a few minutes."),
        (500, "Something went wrong", "An unexpected error occurred. Please try again."),
    ]:
        app.register_error_handler(code, _err(code, title, msg))

    return app
