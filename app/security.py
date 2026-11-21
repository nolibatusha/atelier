"""Authentication, CSRF, rate limiting, access control and security headers."""
import hmac
import secrets
import threading
import time
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

MIN_PASSWORD_LEN = 8


# ---- passwords ---------------------------------------------------------------------------
def hash_password(password):
    return generate_password_hash(password, method="scrypt")


_dummy_hash = None


def verify_password(stored_hash, password):
    return check_password_hash(stored_hash, password)


def burn_password_check():
    """Equalise timing when the account doesn't exist (avoids user enumeration by latency)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password(secrets.token_hex(8))
    check_password_hash(_dummy_hash, "not-the-password")


def password_problem(password):
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(password) > 200:
        return "Password is too long."
    return None


# ---- CSRF --------------------------------------------------------------------------------
def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = session["_csrf"] = secrets.token_urlsafe(32)
    return token


def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf", "")
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            abort(400, "Your session expired or the form was invalid. Please go back and try again.")


# ---- rate limiting (in-process; use a shared store such as Redis behind multiple workers) ---
class RateLimiter:
    def __init__(self):
        self._hits, self._lock = {}, threading.Lock()

    def _prune(self, key, window, now):
        q = [t for t in self._hits.get(key, []) if now - t < window]
        self._hits[key] = q
        return q

    def blocked(self, key, limit, window):
        if not current_app.config.get("RATELIMIT_ENABLED", True):
            return False
        with self._lock:
            return len(self._prune(key, window, time.monotonic())) >= limit

    def hit(self, key, window):
        with self._lock:
            now = time.monotonic()
            self._prune(key, window, now).append(now)

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)

    def clear(self):
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit(name, limit, window):
    """Decorator: count every POST from an IP; respond 429 once over the limit."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if request.method == "POST":
                key = f"{name}:{request.remote_addr}"
                if limiter.blocked(key, limit, window):
                    abort(429, "Too many requests. Please wait a few minutes and try again.")
                limiter.hit(key, window)
            return fn(*a, **kw)

        return wrapper

    return deco


# ---- sessions / users --------------------------------------------------------------------
def load_user():
    g.user, g.customer = None, None
    uid = session.get("uid")
    if not uid:
        return
    db = get_db()
    row = db.execute(
        "SELECT u.*, r.name AS role, r.permissions FROM users u JOIN roles r ON r.id=u.role_id "
        "WHERE u.id=? AND u.is_active=1",
        (uid,),
    ).fetchone()
    if row is None:
        session.pop("uid", None)
        return
    g.user = row
    g.customer = db.execute("SELECT * FROM customers WHERE user_id=?", (uid,)).fetchone()


def login_user(user_id):
    """Rotate the session on login (prevents fixation) but keep the guest-order grants."""
    keep = {k: session[k] for k in ("guest_orders",) if k in session}
    session.clear()
    session.update(keep)
    session["uid"] = user_id
    session.permanent = True
    get_db().execute("UPDATE users SET last_login_at=datetime('now') WHERE id=?", (user_id,))


def logout_user():
    session.clear()


def has_perm(user, perm):
    if not user:
        return False
    perms = set((user["permissions"] or "").split(","))
    return "*" in perms or perm in perms


def is_staff(user):
    return bool(user and user["permissions"])


def customer_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if g.user is None or g.customer is None:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("account.login", next=request.full_path.rstrip("?")))
        return fn(*a, **kw)

    return wrapper


def staff_required(perm=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not is_staff(g.user):
                return redirect(url_for("admin.login", next=request.path))
            if perm and not has_perm(g.user, perm):
                abort(403)
            return fn(*a, **kw)

        return wrapper

    return deco


# ---- headers -----------------------------------------------------------------------------
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; font-src 'self'; form-action 'self'; frame-ancestors 'none'; "
    "base-uri 'self'; object-src 'none'"
)


def add_security_headers(resp):
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    p = request.path
    if p.startswith(("/admin", "/account", "/cart", "/checkout", "/pay", "/order")):
        resp.headers["Cache-Control"] = "no-store"
    return resp
