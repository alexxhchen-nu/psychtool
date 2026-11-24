"""Paste-a-synthetic-block material import via the browser.

The pasted text reuses the exact local import path as a file upload
(identifier scan + redaction + versioned material), and the endpoint refuses
the text unless the caller confirms it is synthetic.
"""

import pytest
from fastapi.testclient import TestClient

from psychtool.server.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_WORKSPACES_DIR", str(tmp_path))
    api = TestClient(create_app())
    assert api.post("/api/workspaces", json={"case_id": "case-a"}).status_code == 201
    return api


def _payload(**overrides):
    return {
        "material_id": "paste-1",
        "title": "Pasted synthetic note",
        "provider": "synthetic author",
        "date": "2026-11-20",
        "text": "Synthetic first paragraph.\n\nSynthetic second paragraph.",
        "synthetic_confirmed": True,
        **overrides,
    }


def test_paste_imports_material_with_passages(client):
    response = client.post("/api/workspaces/case-a/materials/paste", json=_payload())

    assert response.status_code == 200
    material = response.json()["material"]
    assert material["id"] == "paste-1"
    assert material["version"] == 1
    assert [p["text"] for p in material["passages"]] == [
        "Synthetic first paragraph.",
        "Synthetic second paragraph.",
    ]
    assert response.json()["requires_human_review"] is True


def test_paste_requires_synthetic_confirmation(client):
    body = _payload(synthetic_confirmed=False)
    response = client.post("/api/workspaces/case-a/materials/paste", json=body)

    assert response.status_code == 400
    assert "synthetic" in response.json()["detail"]

    omitted = _payload()
    del omitted["synthetic_confirmed"]
    response = client.post("/api/workspaces/case-a/materials/paste", json=omitted)
    assert response.status_code == 400
    assert client.get("/api/workspaces/case-a/materials").json() == []


def test_paste_reuses_identifier_redaction(client):
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json=_payload(text="Call 312-555-0142 about the synthetic fixture."),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["identifier_findings"] == [
        {"category": "telephone", "label": "Telephone numbers"}
    ]
    stored = payload["material"]["passages"][0]["text"]
    assert "312-555-0142" not in stored
    assert "[[TELEPHONE_0]]" in stored


def test_paste_versions_like_uploads(client):
    first = client.post("/api/workspaces/case-a/materials/paste", json=_payload())
    second = client.post(
        "/api/workspaces/case-a/materials/paste",
        json=_payload(text="Revised synthetic paragraph."),
    )

    assert first.json()["material"]["version"] == 1
    assert second.json()["material"]["version"] == 2
    materials = client.get("/api/workspaces/case-a/materials").json()
    assert len(materials) == 1
    assert materials[0]["version"] == 2


def test_paste_rejects_invalid_material_id(client):
    response = client.post(
        "/api/workspaces/case-a/materials/paste", json=_payload(material_id="bad id!")
    )

    assert response.status_code == 400


def test_paste_returns_404_for_unknown_case(client):
    response = client.post("/api/workspaces/no-such-case/materials/paste", json=_payload())

    assert response.status_code == 404
    assert response.json()["detail"] == "case not found"
