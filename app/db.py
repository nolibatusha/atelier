"""SQLite access. One connection per request; explicit, re-entrant transactions."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

ROLES = {
    "admin": "*",
    "manager": "products,inventory,orders,customers,discounts,content",
    "customer": "",
}


def connect(path):
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def bootstrap(conn):
    """Create tables and the built-in roles (application structure, not demo content)."""
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    for name, perms in ROLES.items():
        conn.execute(
            "INSERT INTO roles(name, permissions) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET permissions=excluded.permissions",
            (name, perms),
        )


@contextmanager
def transaction(conn):
    """BEGIN IMMEDIATE takes the write lock up-front, so check-then-update sequences are atomic.
    Re-entrant: an inner call joins the outer transaction."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    conn = connect(app.config["DATABASE"])
    try:
        bootstrap(conn)
    finally:
        conn.close()
