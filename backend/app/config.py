from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
ALLOWED_EMAIL_DOMAIN = "avaipl.com"
INVOICE_BUCKET = "invoices"


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_env() -> None:
    _load_env_file(PROJECT_ROOT / ".env")
    _load_env_file(BACKEND_DIR / ".env")


load_env()


def allowed_email_domain() -> str:
    return os.environ.get("ALLOWED_EMAIL_DOMAIN", ALLOWED_EMAIL_DOMAIN).strip().lower() or ALLOWED_EMAIL_DOMAIN


def is_allowed_org_email(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower().endswith(f"@{allowed_email_domain()}")


def supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").strip()


def supabase_service_role_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def supabase_enabled() -> bool:
    return bool(supabase_url() and supabase_service_role_key())
