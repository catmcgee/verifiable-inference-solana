from __future__ import annotations

import os
import unittest
from http.cookies import SimpleCookie
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import JSONResponse

from server import access


TOKEN = "test-access-token-with-at-least-32-characters"


def request(*, authorization: str | None = None, cookie: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    if cookie is not None:
        headers.append((b"cookie", cookie.encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


class AccessTests(unittest.TestCase):
    def env(self, **overrides: str):
        values = {
            "VINFER_REQUIRE_AUTH": "1",
            "VINFER_AUTH_TOKEN": TOKEN,
            "VINFER_AUTH_SESSION_TTL": "3600",
            "VINFER_AUTH_COOKIE_PATH": "/vinfer",
            "VINFER_AUTH_SECURE_COOKIE": "1",
            **overrides,
        }
        return patch.dict(os.environ, values, clear=False)

    def test_disabled_auth_is_open(self):
        with self.env(VINFER_REQUIRE_AUTH="0"):
            self.assertEqual(access.access_mode(request()), "open")

    def test_config_rejects_short_token(self):
        with self.env(VINFER_AUTH_TOKEN="too-short"):
            with self.assertRaisesRegex(RuntimeError, "at least 32"):
                access.validate_config()

    def test_bearer_auth_is_constant_shape_and_fail_closed(self):
        with self.env():
            access.validate_config()
            self.assertEqual(
                access.access_mode(request(authorization=f"Bearer {TOKEN}")),
                "gateway",
            )
            mode, error = access.require(request(authorization="Bearer wrong"))
            self.assertIsNone(mode)
            self.assertEqual(error.status_code, 401)
            self.assertNotIn(TOKEN, error.body.decode())

    def test_browser_cookie_round_trip_and_logout(self):
        with self.env():
            response = JSONResponse({"ok": True})
            access.set_session_cookie(response)
            parsed = SimpleCookie()
            parsed.load(response.headers["set-cookie"])
            morsel = parsed[access.COOKIE_NAME]
            cookie_header = f"{access.COOKIE_NAME}={morsel.value}"

            self.assertEqual(
                access.access_mode(request(cookie=cookie_header)), "browser-session"
            )
            self.assertTrue(morsel["httponly"])
            self.assertTrue(morsel["secure"])
            self.assertEqual(morsel["samesite"].lower(), "strict")
            self.assertEqual(morsel["path"], "/vinfer")

            logout = JSONResponse({"ok": True})
            access.clear_session_cookie(logout)
            self.assertIn("Max-Age=0", logout.headers["set-cookie"])

    def test_tampered_and_expired_cookies_fail(self):
        with self.env():
            config = access.settings()
            expired = access._session_value(1, config)
            self.assertIsNone(
                access.access_mode(request(cookie=f"{access.COOKIE_NAME}={expired}"))
            )
            current = access._session_value(4_000_000_000, config)
            tampered = current[:-1] + ("A" if current[-1] != "A" else "B")
            self.assertIsNone(
                access.access_mode(request(cookie=f"{access.COOKIE_NAME}={tampered}"))
            )


if __name__ == "__main__":
    unittest.main()
