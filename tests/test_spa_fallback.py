"""SPA fallback must serve index.html for pages but never for /api/* paths."""

import importlib

import pytest
from fastapi.testclient import TestClient

app_module = importlib.import_module("psychtool.server.app")
from psychtool.server.app import create_app


@pytest.fixture
def spa_client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa-shell</html>", encoding="utf-8")
    (dist / "favicon.ico").write_bytes(b"ico")
    monkeypatch.setattr(app_module, "_WEB_DIST", dist)
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    return TestClient(create_app())


def test_unknown_api_path_returns_json_404(spa_client):
    response = spa_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert response.headers["content-type"].startswith("application/json")


def test_normalized_traversal_path_returns_json_404(spa_client):
    # ``..%2Fx`` normalizes to /api/x before routing; the fallback must not
    # answer it with the SPA shell.
    response = spa_client.get("/api/workspaces/..%2Fx/materials")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_spa_page_still_returns_index(spa_client):
    response = spa_client.get("/some/page")
    assert response.status_code == 200
    assert "spa-shell" in response.text


def test_real_asset_file_still_served(spa_client):
    response = spa_client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.content == b"ico"


def test_real_api_routes_unaffected(spa_client):
    assert spa_client.get("/api/health").status_code == 200
    assert spa_client.get("/api/workspaces").status_code == 200
