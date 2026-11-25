"""Case-scoped API: materials, claims, and section persistence (SQLite store)."""

import importlib

import pytest
from fastapi.testclient import TestClient

from psychtool.core.workspace import Passage
from psychtool.server.app import create_app
from psychtool.store.sqlite_store import SqliteStore


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    return TestClient(create_app())


def _workspace(tmp_path, monkeypatch):
    """Seed one case with a material and one claim through the store."""
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    store = SqliteStore(tmp_path / "psychtool.db")
    store.create_case("case-a")
    case = store.case("case-a")
    case.import_material(
        material_id="doc-1",
        title="Intake",
        provider="self",
        date="2026-10-01",
        passages=[Passage(id="p001", text="first paragraph"),
                  Passage(id="p002", text="second paragraph")],
    )
    case.add_claim(
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
    return case


def test_list_workspaces(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    response = _client(tmp_path, monkeypatch).get("/api/workspaces")
    assert response.status_code == 200
    assert response.json() == [{"case_id": "case-a"}]


def test_list_materials(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    response = _client(tmp_path, monkeypatch).get("/api/workspaces/case-a/materials")
    assert response.status_code == 200
    assert [m["id"] for m in response.json()] == ["doc-1"]


def test_list_claims(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    response = _client(tmp_path, monkeypatch).get("/api/workspaces/case-a/claims")
    assert response.status_code == 200
    assert [c["id"] for c in response.json()] == ["c1"]


def test_section_states_default_empty(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    response = _client(tmp_path, monkeypatch).get(
        "/api/workspaces/case-a/sections", params={"template_id": "intake-report"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["section_id"] == "header"
    assert all(s["status"] == "empty" for s in payload)


def test_put_section_persists(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    body = {
        "template_id": "intake-report",
        "template_version": 1,
        "text": "draft text",
        "claim_ids": ["c1"],
        "status": "draft",
    }
    response = client.put("/api/workspaces/case-a/sections/history", json=body)
    assert response.status_code == 200
    assert response.json()["version"] == 1

    states = client.get(
        "/api/workspaces/case-a/sections", params={"template_id": "intake-report"}
    ).json()
    background = next(s for s in states if s["section_id"] == "history")
    assert background["status"] == "draft"
    assert background["text"] == "draft text"
    assert background["claim_ids"] == ["c1"]


def test_put_section_unknown_claim_is_400(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    body = {
        "template_id": "intake-report",
        "template_version": 1,
        "text": "x",
        "claim_ids": ["missing"],
    }
    response = client.put("/api/workspaces/case-a/sections/history", json=body)
    assert response.status_code == 400


def test_case_id_cannot_escape_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    store = SqliteStore(tmp_path / "psychtool.db")

    with pytest.raises(ValueError):
        store.case("../escape")


def test_names_endpoint_roundtrip(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/workspaces/case-a/names").json() == {"names": []}
    response = client.put(
        "/api/workspaces/case-a/names", json={"names": ["Jane Doe", "Dr. Smith", "jane doe"]}
    )
    assert response.status_code == 200
    assert response.json() == {"names": ["Dr. Smith", "Jane Doe"]}


def test_generate_endpoint_is_gone_without_calling_model(monkeypatch, tmp_path):
    _workspace(tmp_path, monkeypatch)
    calls = []
    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(
        app_module,
        "http_transport",
        lambda config, envelope: calls.append((config, envelope)),
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/workspaces/case-a/sections/history/generate",
        json={
            "template_id": "intake-report",
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
