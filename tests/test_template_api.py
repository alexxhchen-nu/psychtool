"""Web API routes for report-template discovery."""

from fastapi.testclient import TestClient

from psychtool.server.app import create_app
from tests.conftest import build_client


def test_list_templates_endpoint():
    response = build_client(create_app()).get("/api/templates")
    assert response.status_code == 200
    payload = response.json()
    assert [item["template_id"] for item in payload] == ["intake-report"]
    assert "source_snapshot" not in payload[0]


def test_get_template_endpoint():
    response = build_client(create_app()).get("/api/templates/intake-report")
    assert response.status_code == 200
    assert response.json()["sections"][0]["id"] == "header"


def test_unknown_template_is_404():
    response = build_client(create_app()).get("/api/templates/missing")
    assert response.status_code == 404
