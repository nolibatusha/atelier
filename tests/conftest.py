import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from app.db import bootstrap, connect  # noqa: E402
from seed.run import seed  # noqa: E402

ADMIN = ("admin@example.com", "ChangeMe-Demo-2026!")
MANAGER = ("manager@example.com", "Manager-Demo-2026!")
CUSTOMER = ("customer@example.com", "Customer-Demo-2026!")


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    d = tmp_path_factory.mktemp("tmpl")
    conn = connect(str(d / "t.db"))
    bootstrap(conn)
    seed(conn, str(d / "up"), ADMIN[0], ADMIN[1], MANAGER[1], CUSTOMER[1], with_images=False)
    conn.close()
    return d / "t.db"


@pytest.fixture()
def app(tmp_path, template_db):
    import shutil
    db = tmp_path / "store.db"
    shutil.copy(template_db, db)
    a = create_app({"TESTING": True, "DATABASE": str(db), "UPLOAD_DIR": str(tmp_path / "up"),
                    "SECRET_KEY": "test-secret", "RATELIMIT_ENABLED": False})
    from app.security import limiter
    limiter.clear()
    return a


@pytest.fixture()
def client(app):
    return app.test_client()


class Helper:
    def __init__(self, app):
        self.app = app

    def q(self, sql, *args):
        from app.db import connect
        c = connect(self.app.config["DATABASE"])
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def token(self, client):
        with client.session_transaction() as s:
            if not s.get("_csrf"):
                s["_csrf"] = "tok-" + "x" * 30
            return s["_csrf"]

    def post(self, client, url, data=None, **kw):
        data = dict(data or {})
        data["_csrf"] = self.token(client)
        return client.post(url, data=data, **kw)

    def login(self, client, creds, url="/account/login"):
        return self.post(client, url, {"email": creds[0], "password": creds[1]})

    def variant(self, in_stock=True, min_stock=3):
        rows = self.q("SELECT v.id, v.stock, p.slug FROM product_variants v JOIN products p ON p.id=v.product_id "
                      "WHERE p.is_published=1 AND v.is_active=1 AND v.stock %s ORDER BY v.id" % (f">= {min_stock}" if in_stock else "= 0"))
        return rows[0]


@pytest.fixture()
def h(app):
    return Helper(app)


CHECKOUT = {"email": "buyer@example.org", "phone": "+1 555 0100", "ship_name": "Test Buyer", "ship_line1": "1 Test Street",
            "ship_city": "Testville", "ship_postal": "12345", "ship_country": "Germany", "payment_method": "card_demo"}


def fill_checkout(h, client, **over):
    ship = h.q("SELECT id FROM shipping_methods WHERE is_active=1 ORDER BY sort_order LIMIT 1")[0]["id"]
    d = dict(CHECKOUT, shipping_method_id=ship)
    d.update(over)
    return d
