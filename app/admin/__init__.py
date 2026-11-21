"""Admin back-office. Every route is behind staff_required(<permission>); login lives at /admin/login."""
from flask import Blueprint

bp = Blueprint("admin", __name__, url_prefix="/admin")

from . import auth, catalog, sales, site  # noqa: E402,F401  (register routes)
