"""Local security baseline (ADR 0011): loopback Host check, per-start
session token, and strict security headers.

The API binds 127.0.0.1 only (see ``server/main.py``), but a bound port is
still reachable by any local process and — through DNS rebinding or a
browser proxying localhost — by web pages. Three cheap controls close that:

- every request's ``Host`` header must resolve to a loopback name
  (``127.0.0.1``, ``localhost``, ``[::1]``), so a rebinding attack that
  reaches the socket still fails the check;
- every ``/api/*`` request except ``GET /api/health`` must carry the
  per-start session token in ``X-Psychtool-Token`` (constant-time compare).
  The browser gets the token from a ``<meta name="psychtool-session">`` tag
  the server injects into the SPA's index.html; the token is never logged;
- strict CSP and related headers on every response, and the SPA index is
  served ``Cache-Control: no-store`` so a stale shell never carries an old
  token.

There is deliberately no CORS middleware: the SPA is same-origin with the
API, and no cross-origin caller should be able to read responses.
"""

from __future__ import annotations

import html
import os
import re
import secrets

from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

SESSION_HEADER = "X-Psychtool-Token"
SESSION_ENV = "PSYCHTOOL_SESSION_TOKEN"
SESSION_META_NAME = "psychtool-session"

_LOOPBACK_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
_API_PREFIX = "/api/"
_HEALTH_PATH = "/api/health"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def resolve_session_token(provided: str | None = None) -> tuple[str, str]:
    """Return ``(token, source)`` where source is 'provided' | 'env' | 'generated'.

    The environment variable is a dev-only convenience so the Vite dev proxy
    can share one token with the backend; it must be at least 32 characters.
    The token value itself is never logged.
    """
    if provided is not None:
        if len(provided) < 32:
            raise ValueError("session token must be at least 32 characters")
        return provided, "provided"
    from_env = os.environ.get(SESSION_ENV)
    if from_env:
        if len(from_env) < 32:
            raise ValueError(
                f"{SESSION_ENV} must be at least 32 characters when set"
            )
        return from_env, "env"
    return secrets.token_urlsafe(32), "generated"


def host_is_loopback(host_header: str | None) -> bool:
    """True when the Host header's hostname part is a loopback name."""
    if not host_header:
        return False
    value = host_header.strip()
    if not value:
        return False
    if value.startswith("["):  # bracketed IPv6, e.g. [::1]:8000
        end = value.find("]")
        if end == -1:
            return False
        hostname, rest = value[1:end], value[end + 1:]
        port = rest[1:] if rest.startswith(":") else None
        if rest and port is None:
            return False
    else:
        hostname, _, port = value.partition(":")
        port = port if ":" in value else None
    # The optional port must be plain digits: "127.0.0.1:80@evil" is refused.
    if port is not None and not (port.isascii() and port.isdigit()):
        return False
    return hostname.lower() in _LOOPBACK_HOSTNAMES


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    """Host check (all requests), token check (/api/*), security headers."""

    def __init__(self, app, session_token: str) -> None:
        super().__init__(app)
        self._session_token = session_token

    async def dispatch(self, request: Request, call_next) -> Response:
        if not host_is_loopback(request.headers.get("host")):
            return JSONResponse(
                {"detail": "invalid host"}, status_code=400, headers=SECURITY_HEADERS
            )
        path = request.url.path
        if path.startswith(_API_PREFIX) and path != _HEALTH_PATH:
            presented = request.headers.get(SESSION_HEADER, "")
            # Compare bytes: str compare_digest raises on non-ASCII input,
            # which would turn a bad token into a 500 instead of a 401.
            if not secrets.compare_digest(
                presented.encode("utf-8", "surrogateescape"),
                self._session_token.encode("utf-8"),
            ):
                return JSONResponse(
                    {"detail": "unauthorized"},
                    status_code=401,
                    headers=SECURITY_HEADERS,
                )
        # Security headers are set by SecurityHeadersASGIMiddleware, which
        # also covers the fixed 500 sent by ServerErrorMiddleware.
        return await call_next(request)


class SecurityHeadersASGIMiddleware:
    """Pure-ASGI header injection that also covers error responses.

    Registered as the outermost middleware (before ``ServerErrorMiddleware``
    is appended by Starlette), so it wraps ``send`` for *every* response —
    including the fixed 500 that ``ServerErrorMiddleware`` renders when an
    exception escapes the app. ``BaseHTTPMiddleware`` cannot do this: on an
    unhandled exception ``call_next`` raises and the error response is sent
    by the outer layer, bypassing ``dispatch``'s return path.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message.setdefault("headers", []))
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


def inject_session_meta(index_html: str, session_token: str) -> str:
    """Insert the session-token meta tag into the SPA shell's <head>."""
    meta = (
        f'<meta name="{SESSION_META_NAME}" '
        f'content="{html.escape(session_token, quote=True)}" />'
    )
    pattern = re.compile(r"<head[^>]*>", re.IGNORECASE)
    match = pattern.search(index_html)
    if match is None:
        # A shell without <head> still works; the meta lands first in body.
        return meta + index_html
    return index_html[: match.end()] + meta + index_html[match.end():]
