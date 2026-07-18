"""Authentication for non-payment access to inference endpoints.

The public pay gateway authenticates to the origin with a strong bearer token
after it has verified payment. The browser exchanges a separate operator code
for a short-lived, HttpOnly session cookie signed by that bearer token. No
credential is embedded in the static frontend or persisted by the server.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse, Response


COOKIE_NAME = "vinfer_test_session"
DEFAULT_TTL_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class AccessSettings:
    required: bool
    token: str
    browser_code: str
    ttl_seconds: int
    cookie_path: str
    secure_cookie: bool


def settings() -> AccessSettings:
    token = os.environ.get("VINFER_AUTH_TOKEN", "")
    return AccessSettings(
        required=os.environ.get("VINFER_REQUIRE_AUTH", "0") == "1",
        token=token,
        browser_code=os.environ.get("VINFER_ACCESS_CODE", token),
        ttl_seconds=int(os.environ.get("VINFER_AUTH_SESSION_TTL", DEFAULT_TTL_SECONDS)),
        cookie_path=os.environ.get("VINFER_AUTH_COOKIE_PATH", "/"),
        secure_cookie=os.environ.get("VINFER_AUTH_SECURE_COOKIE", "1") == "1",
    )


def validate_config() -> None:
    config = settings()
    if not config.required:
        return
    if len(config.token) < 32:
        raise RuntimeError(
            "VINFER_AUTH_TOKEN must contain at least 32 characters when "
            "VINFER_REQUIRE_AUTH=1"
        )
    if len(config.browser_code) < 10:
        raise RuntimeError(
            "VINFER_ACCESS_CODE must contain at least 10 characters when "
            "VINFER_REQUIRE_AUTH=1"
        )
    if config.ttl_seconds < 60:
        raise RuntimeError("VINFER_AUTH_SESSION_TTL must be at least 60 seconds")
    if not config.cookie_path.startswith("/"):
        raise RuntimeError("VINFER_AUTH_COOKIE_PATH must be an absolute URL path")


def _signature(expires_at: int, config: AccessSettings) -> str:
    digest = hmac.new(
        config.token.encode(), f"v1:{expires_at}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _session_value(expires_at: int, config: AccessSettings) -> str:
    return f"v1.{expires_at}.{_signature(expires_at, config)}"


def _valid_session(value: str | None, config: AccessSettings) -> bool:
    if not value:
        return False
    try:
        version, raw_expiry, supplied = value.split(".", 2)
        expires_at = int(raw_expiry)
    except (TypeError, ValueError):
        return False
    if version != "v1" or expires_at <= int(time.time()):
        return False
    return hmac.compare_digest(supplied, _signature(expires_at, config))


def _bearer_token(request: Request) -> str | None:
    scheme, separator, credential = request.headers.get("authorization", "").partition(
        " "
    )
    if not separator or scheme.lower() != "bearer":
        return None
    return credential.strip() or None


def access_mode(request: Request) -> str | None:
    """Return the accepted access mechanism, or ``None`` when unauthorized."""
    config = settings()
    if not config.required:
        return "open"
    bearer = _bearer_token(request)
    if bearer is not None and hmac.compare_digest(bearer, config.token):
        return "gateway"
    if _valid_session(request.cookies.get(COOKIE_NAME), config):
        return "browser-session"
    return None


def require(request: Request) -> tuple[str | None, JSONResponse | None]:
    mode = access_mode(request)
    if mode is not None:
        return mode, None
    return None, JSONResponse(
        status_code=401,
        content={
            "error": "authentication required",
            "auth": "browser-session-or-bearer",
        },
        headers={
            "WWW-Authenticate": 'Bearer realm="verified-inference-origin"',
            "Cache-Control": "no-store, private",
        },
    )


def access_code_valid(access_code: str) -> bool:
    config = settings()
    return (
        not config.required
        or bool(access_code)
        and hmac.compare_digest(access_code, config.browser_code)
    )


def set_session_cookie(response: Response) -> int:
    config = settings()
    expires_at = int(time.time()) + config.ttl_seconds
    response.set_cookie(
        key=COOKIE_NAME,
        value=_session_value(expires_at, config),
        max_age=config.ttl_seconds,
        expires=expires_at,
        path=config.cookie_path,
        secure=config.secure_cookie,
        httponly=True,
        samesite="strict",
    )
    return expires_at


def clear_session_cookie(response: Response) -> None:
    config = settings()
    response.delete_cookie(
        key=COOKIE_NAME,
        path=config.cookie_path,
        secure=config.secure_cookie,
        httponly=True,
        samesite="strict",
    )
