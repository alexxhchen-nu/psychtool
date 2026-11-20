"""Workspace-scoped API: materials, claims, and section persistence."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from psychtool.core.workspace import init_workspace, import_material
from psychtool.core.claims import add_claim
from psychtool.server.app import create_app, _workspace_path


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_WORKSPACES_DIR", str(tmp_path))
    return TestClient(create_app())


def _workspace(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    import_material(
        ws,
        material_id="doc-1",
        title="Intake",
        provider="self",
        date="2026-10-01",
        text="first paragraph\n\nsecond paragraph",
    )
    add_claim(
        ws,
        claim_id="c1",
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-10-01",
        category="client_statement",
        topic="history",
        text="statement",
    )
    return ws


def test_list_workspaces(tmp_path, monkeypatch):
    _workspace(tmp_path)
    response = _client(tmp_path, monkeypatch).get("/api/workspaces")
    assert response.status_code == 200
    assert response.json() == [{"case_id": "case-a"}]


def test_list_materials(tmp_path, monkeypatch):
    _workspace(tmp_path)
    response = _client(tmp_path, monkeypatch).get("/api/workspaces/case-a/materials")
    assert response.status_code == 200
    assert [m["id"] for m in response.json()] == ["doc-1"]


def test_list_claims(tmp_path, monkeypatch):
    _workspace(tmp_path)
    response = _client(tmp_path, monkeypatch).get("/api/workspaces/case-a/claims")
    assert response.status_code == 200
    assert [c["id"] for c in response.json()] == ["c1"]


def test_section_states_default_empty(tmp_path, monkeypatch):
    _workspace(tmp_path)
    response = _client(tmp_path, monkeypatch).get(
        "/api/workspaces/case-a/sections", params={"template_id": "ew-report"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["section_id"] == "report_header"
    assert all(s["status"] == "empty" for s in payload)


def test_put_section_persists(tmp_path, monkeypatch):
    _workspace(tmp_path)
    client = _client(tmp_path, monkeypatch)
    body = {
        "template_id": "ew-report",
        "template_version": 1,
        "text": "draft text",
        "claim_ids": ["c1"],
        "status": "draft",
    }
    response = client.put("/api/workspaces/case-a/sections/background_information", json=body)
    assert response.status_code == 200
    assert response.json()["version"] == 1

    states = client.get(
        "/api/workspaces/case-a/sections", params={"template_id": "ew-report"}
    ).json()
    background = next(s for s in states if s["section_id"] == "background_information")
    assert background["status"] == "draft"
    assert background["text"] == "draft text"
    assert background["claim_ids"] == ["c1"]


def test_put_section_unknown_claim_is_400(tmp_path, monkeypatch):
    _workspace(tmp_path)
    client = _client(tmp_path, monkeypatch)
    body = {
        "template_id": "ew-report",
        "template_version": 1,
        "text": "x",
        "claim_ids": ["missing"],
    }
    response = client.put("/api/workspaces/case-a/sections/background_information", json=body)
    assert response.status_code == 400


def test_case_id_cannot_escape_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_WORKSPACES_DIR", str(tmp_path))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _workspace_path("../escape")
    assert exc.value.status_code == 400


def test_names_endpoint_roundtrip(tmp_path, monkeypatch):
    _workspace(tmp_path)
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/workspaces/case-a/names").json() == {"names": []}
    response = client.put(
        "/api/workspaces/case-a/names", json={"names": ["Jane Doe", "Dr. Smith", "jane doe"]}
    )
    assert response.status_code == 200
    assert response.json() == {"names": ["Dr. Smith", "Jane Doe"]}


def test_generate_endpoint_is_gone_without_calling_model(monkeypatch, tmp_path):
    _workspace(tmp_path)
    monkeypatch.setenv("PSYCHTOOL_WORKSPACES_DIR", str(tmp_path))
    calls = []
    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(
        app_module,
        "http_transport",
        lambda config, envelope: calls.append((config, envelope)),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/workspaces/case-a/sections/background_information/generate",
        json={
            "template_id": "ew-report",
            "template_version": 1,
            "claim_ids": ["c1"],
            "instructions": "write background",
        },
    )

    assert response.status_code == 410
    assert "prepare" in response.json()["detail"]
    assert "approve" in response.json()["detail"]
    assert "send" in response.json()["detail"]
    assert calls == []
