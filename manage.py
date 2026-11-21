#!/usr/bin/env python3
"""Command-line management: run, initdb, seed, createadmin, reset.

  python manage.py seed            # load the fictional ATELIER demo store (empty database only)
  python manage.py run             # start the dev server on http://127.0.0.1:5000
  python manage.py createadmin     # create/update an admin user from ADMIN_EMAIL / ADMIN_PASSWORD
  python manage.py reset           # delete the database + uploads, then seed again
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app  # noqa: E402
from app.config import build_config  # noqa: E402
from app.db import bootstrap, connect  # noqa: E402
from app.security import hash_password, password_problem  # noqa: E402

DEMO_ADMIN_EMAIL = "admin@example.com"
DEMO_ADMIN_PASSWORD = "ChangeMe-Demo-2026!"
DEMO_MANAGER_PASSWORD = "Manager-Demo-2026!"
DEMO_CUSTOMER_PASSWORD = "Customer-Demo-2026!"


def cmd_seed(args):
    from seed.run import is_empty, seed

    cfg = build_config()
    conn = connect(cfg["DATABASE"])
    bootstrap(conn)
    if not is_empty(conn):
        print("Database already has data. Use `python manage.py reset` to start over.")
        return 1
    email = os.environ.get("ADMIN_EMAIL", DEMO_ADMIN_EMAIL)
    password = os.environ.get("ADMIN_PASSWORD", DEMO_ADMIN_PASSWORD)
    seed(conn, cfg["UPLOAD_DIR"], email, password, DEMO_MANAGER_PASSWORD, DEMO_CUSTOMER_PASSWORD, with_images=not args.no_images)
    print("Demo store seeded.\n")
    print(f"  Admin      {email} / {password}     ->  /admin")
    print(f"  Manager    manager@example.com / {DEMO_MANAGER_PASSWORD}   (limited permissions)")
    print(f"  Customer   customer@example.com / {DEMO_CUSTOMER_PASSWORD}  ->  /account")
    print("\nChange these before any real deployment.")
    return 0


def cmd_reset(args):
    cfg = build_config()
    for suffix in ("", "-wal", "-shm"):
        Path(cfg["DATABASE"] + suffix).unlink(missing_ok=True)
    shutil.rmtree(cfg["UPLOAD_DIR"], ignore_errors=True)
    return cmd_seed(args)


def cmd_createadmin(args):
    cfg = build_config()
    conn = connect(cfg["DATABASE"])
    bootstrap(conn)
    email = (args.email or os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = args.password or os.environ.get("ADMIN_PASSWORD") or ""
    if not email or (problem := password_problem(password)):
        print(problem or "Provide --email and --password (or ADMIN_EMAIL / ADMIN_PASSWORD).")
        return 1
    role = conn.execute("SELECT id FROM roles WHERE name='admin'").fetchone()["id"]
    conn.execute(
        "INSERT INTO users(email, password_hash, name, role_id) VALUES(?,?,?,?) "
        "ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash, role_id=excluded.role_id, is_active=1",
        (email, hash_password(password), "Administrator", role))
    print(f"Admin user ready: {email}")
    return 0


def cmd_run(args):
    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("seed", cmd_seed), ("reset", cmd_reset)):
        sp = sub.add_parser(name)
        sp.add_argument("--no-images", action="store_true", help="skip generating placeholder imagery")
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("createadmin")
    sp.add_argument("--email")
    sp.add_argument("--password")
    sp.set_defaults(fn=cmd_createadmin)
    sp = sub.add_parser("run")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=5000)
    sp.add_argument("--debug", action="store_true")
    sp.set_defaults(fn=cmd_run)
    sub.add_parser("initdb").set_defaults(fn=lambda a: (bootstrap(connect(build_config()["DATABASE"])), print("Database ready."), 0)[2])
    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
