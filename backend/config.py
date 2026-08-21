"""Runtime configuration, entirely env-driven.

Nothing here is hardcoded to a domain or an address on purpose: the site
starts its life on `chef.montaigu.org` and is expected to move to the
chef's own domain later. That move must be a change of environment
variables on the Coolify side, never a code change.
"""

import os
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Paris"))

# Where SQLite lives. Mounted as a volume in production -- see Dockerfile.
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DATA_DIR, "chef.db")

# Editable site copy (prestations, tarifs, about...). Read from disk on every
# request in dev so a change shows up on reload; cached in production.
CONTENT_PATH = os.environ.get(
    "CONTENT_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "content", "site.json"),
)

DEV = os.environ.get("DEV", "").lower() in ("1", "true", "yes")

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")

# --- Admin back-office -------------------------------------------------
# Single operator, single password. No user table, no signup.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# Signs the session cookie. Generated per-deploy if unset, which logs the
# admin out on every redeploy -- acceptable, but set it in production.
SECRET_KEY = os.environ.get("SECRET_KEY", "")
SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "72"))
SESSION_COOKIE = "chef_admin"

# --- Mail --------------------------------------------------------------
# Unset SMTP_HOST disables sending entirely. That is a supported mode (it is
# the default in dev), but it is never silent: every booking records why its
# mail did not go out, and the back-office shows the failures.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "").lower() in ("1", "true", "yes")
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "8"))  # inline on the booking path: keep it short

MAIL_FROM = os.environ.get("MAIL_FROM", "chef@montaigu.org")
MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "")
# Where booking notifications land: the chef's own mailbox.
MAIL_TO = os.environ.get("MAIL_TO", "")


def mail_enabled() -> bool:
    return bool(SMTP_HOST)
