"""Environment-driven configuration. No secrets are hardcoded; see .env.example."""
import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path=None):
    """Tiny .env loader (avoids an extra dependency). Existing env vars win."""
    path = Path(path or BASE_DIR / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #")[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def build_config(overrides=None):
    load_dotenv()
    overrides = overrides or {}
    env = os.environ.get("APP_ENV", "development")
    instance = Path(os.environ.get("INSTANCE_DIR", BASE_DIR / "instance"))
    instance.mkdir(parents=True, exist_ok=True)

    secret = overrides.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
    if not secret:
        if env == "production":
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
        keyfile = instance / "dev_secret_key"  # stable across dev restarts, never committed
        if not keyfile.exists():
            keyfile.write_text(secrets.token_hex(32))
            keyfile.chmod(0o600)
        secret = keyfile.read_text(encoding="utf-8").strip()

    cfg = dict(
        ENV=env,
        SECRET_KEY=secret,
        DATABASE=os.environ.get("DATABASE_PATH", str(instance / "store.db")),
        UPLOAD_DIR=os.environ.get("UPLOAD_DIR", str(instance / "uploads")),
        MAX_CONTENT_LENGTH=24 * 1024 * 1024,  # whole request (several images)
        MAX_IMAGE_BYTES=6 * 1024 * 1024,       # per uploaded image
        SESSION_COOKIE_NAME="store_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(env == "production") or os.environ.get("COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        TRUSTED_PROXIES=int(os.environ.get("TRUSTED_PROXIES", "0") or 0),
        RATELIMIT_ENABLED=True,
        PER_PAGE=12,
        MAX_LINE_QTY=10,
        ALLOW_SIMULATED_PAYMENTS=os.environ.get("ALLOW_SIMULATED_PAYMENTS") == "1",
        TESTING=False,
    )
    cfg.update(overrides)
    return cfg
