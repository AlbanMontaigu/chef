"""Back-office authentication: one password, one signed cookie.

There is exactly one operator, so there is no user table and no signup. The
cookie carries an expiry and an HMAC over it -- the server keeps no session
state, which means a redeploy does not log the chef out (as long as
SECRET_KEY is set in the environment).
"""

import base64
import hmac
import logging
import os
import secrets
import time
from hashlib import sha256

from fastapi import Request

from . import config

log = logging.getLogger("chef.auth")

# Falling back to a random key is deliberate: an unset SECRET_KEY must never
# mean "unsigned cookies", it means "sessions do not survive a restart".
_SECRET = (config.SECRET_KEY or secrets.token_hex(32)).encode()
if not config.SECRET_KEY:
    log.warning("SECRET_KEY unset -- admin sessions will not survive a restart")

# Brute-force brake. In-memory and per-process, which is enough for a single
# container: the point is to make an online guessing attack impractical.
_FAILURES: dict[str, list[float]] = {}
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 900


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def configured() -> bool:
    return bool(config.ADMIN_PASSWORD)


def locked_out(ip: str) -> int:
    """Remaining lockout in seconds, 0 if the caller may try again."""
    now = time.time()
    recent = [t for t in _FAILURES.get(ip, []) if now - t < _LOCKOUT_SECONDS]
    _FAILURES[ip] = recent
    if len(recent) < _MAX_FAILURES:
        return 0
    return int(_LOCKOUT_SECONDS - (now - recent[0]))


def record_failure(ip: str) -> None:
    _FAILURES.setdefault(ip, []).append(time.time())


def clear_failures(ip: str) -> None:
    _FAILURES.pop(ip, None)


def check_password(candidate: str) -> bool:
    if not configured():
        return False
    return hmac.compare_digest(candidate.encode(), config.ADMIN_PASSWORD.encode())


def issue_token() -> str:
    expires = int(time.time()) + config.SESSION_HOURS * 3600
    payload = f"{expires}.{secrets.token_hex(8)}"
    sig = hmac.new(_SECRET, payload.encode(), sha256).digest()
    return f"{_b64(payload.encode())}.{_b64(sig)}"


def valid_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    body, _, sig = token.rpartition(".")
    try:
        payload = _unb64(body)
        given = _unb64(sig)
    except (ValueError, TypeError):
        return False
    expected = hmac.new(_SECRET, payload, sha256).digest()
    if not hmac.compare_digest(given, expected):
        return False
    try:
        expires = int(payload.decode().split(".", 1)[0])
    except (ValueError, UnicodeDecodeError):
        return False
    return expires > time.time()


def is_authenticated(request: Request) -> bool:
    return valid_token(request.cookies.get(config.SESSION_COOKIE))


def client_ip(request: Request) -> str:
    # Behind Traefik; the first hop in X-Forwarded-For is the real client.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def secure_cookies() -> bool:
    return config.PUBLIC_URL.startswith("https://")
