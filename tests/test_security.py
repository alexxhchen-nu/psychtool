"""S3 security baseline tests: session token, Host check, CSP headers.

Covers: 401 on every /api route except health without/with a wrong token;
the token value never appearing in captured logs; Host-header allow/deny on
API and SPA paths; security headers on API, index and asset responses; the
SPA index carrying the token meta tag with ``Cache-Control: no-store``; and
``main`` refusing a non-loopback bind host.
"""

from __future__ import annotations

import importlib
import logging

import pytest
from fastapi.testclient import TestClient

from psychtool.server import main as server_main
from psychtool.server.app import create_app
from psychtool.server.security import SESSION_HEADER
from tests.conftest import build_client

app_module = importlib.import_module("psychtool.server.app")

_API_ROUTES = [
    ("GET", "/api/templates"),
    ("GET", "/api/templates/intake-report"),
    ("GET", "/api/workspaces"),
    ("POST", "/api/workspaces"),
    ("GET", "/api/workspaces/case-a/materials"),
    ("POST", "/api/workspaces/case-a/materials/paste"),
    ("GET", "/api/workspaces/case-a/claims"),
    ("GET", "/api/workspaces/case-a/materials/doc-1/suggestions?provider_role=self_report"),
    ("POST", "/api/workspaces/case-a/claims"),
    ("GET", "/api/workspaces/case-a/names"),
    ("PUT", "/api/workspaces/case-a/names"),
    ("GET", "/api/workspaces/case-a/sections?template_id=intake-report"),
    ("PUT", "/api/workspaces/case-a/sections/history"),
    ("POST", "/api/workspaces/case-a/egress/prepare"),
    ("GET", "/api/workspaces/case-a/egress/req-1"),
    ("POST", "/api/workspaces/case-a/egress/req-1/approve"),
    ("POST", "/api/workspaces/case-a/egress/req-1/send"),
    ("POST", "/api/workspaces/case-a/sections/history/generate"),
]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.mark.parametrize(("method", "path"), _API_ROUTES)
def test_api_requires_token(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}
    response = client.request(method, path, headers={SESSION_HEADER: "wrong-token" * 4})
    assert response.status_code == 401


def test_health_needs_no_token(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_correct_token_works(client, app):
    response = client.get("/api/workspaces", headers={SESSION_HEADER: app.state.session_token})
    assert response.status_code == 200


def test_token_never_appears_in_logs(app, client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.get("/api/workspaces")
        client.get("/api/workspaces", headers={SESSION_HEADER: app.state.session_token})
        client.get("/api/health")
    for record in caplog.records:
        assert app.state.session_token not in record.getMessage()


def test_explicit_token_argument_is_used(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    token = "t" * 40
    app = create_app(session_token=token)
    assert app.state.session_token == token
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/workspaces", headers={SESSION_HEADER: token}).status_code == 200
    assert client.get("/api/workspaces", headers={SESSION_HEADER: "x" * 40}).status_code == 401


def test_env_token_used_when_long_enough(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    token = "e" * 32
    monkeypatch.setenv("PSYCHTOOL_SESSION_TOKEN", token)
    app = create_app()
    assert app.state.session_token == token
    assert app.state.session_token_source == "env"


def test_short_env_token_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    monkeypatch.setenv("PSYCHTOOL_SESSION_TOKEN", "short")
    with pytest.raises(ValueError):
        create_app()


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "localhost.evil"])
def test_host_check_rejects_non_loopback(client, app, host):
    assert client.get("/api/health", headers={"host": host}).status_code == 400
    assert client.get("/", headers={"host": host}).status_code == 400
    response = client.get("/api/workspaces", headers={"host": host, SESSION_HEADER: app.state.session_token})
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid host"}


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:5173", "[::1]:8000"])
def test_host_check_accepts_loopback(client, host):
    assert client.get("/api/health", headers={"host": host}).status_code == 200


def test_security_headers_on_api_response(client):
    response = client.get("/api/health")
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert "object-src 'none'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.fixture
def spa_client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<html><head><title>t</title></head><body><div id=\"root\"></div></body></html>",
        encoding="utf-8",
    )
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('x')", encoding="utf-8")
    monkeypatch.setattr(app_module, "_WEB_DIST", dist)
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    application = create_app()
    return application, TestClient(application, base_url="http://127.0.0.1")


def test_index_has_token_meta_no_store_and_headers(spa_client):
    app, client = spa_client
    response = client.get("/")
    assert response.status_code == 200
    assert f'<meta name="psychtool-session" content="{app.state.session_token}" />' in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "content-security-policy" in response.headers
    assert response.headers["x-frame-options"] == "DENY"


def test_asset_has_security_headers(spa_client):
    _, client = spa_client
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "content-security-policy" in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


def test_spa_fallback_response_has_headers_and_token(spa_client):
    app, client = spa_client
    response = client.get("/some/client/route")
    assert response.status_code == 200
    assert "content-security-policy" in response.headers
    assert app.state.session_token in response.text


def test_main_refuses_non_loopback_host(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_HOST", "0.0.0.0")
    with pytest.raises(SystemExit):
        server_main.main()


def test_main_refuses_public_hostname(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_HOST", "example.com")
    with pytest.raises(SystemExit):
        server_main.main()
