"""Web API tests for staged, persisted model egress requests."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from psychtool.core.claims import add_claim
from psychtool.core.workspace import import_material, init_workspace, set_known_names
from psychtool.server.app import create_app


_ENV_VARS = (
    "PSYCHTOOL_BASE_URL",
    "PSYCHTOOL_MODEL",
    "PSYCHTOOL_JUDGE_MODEL",
    "PSYCHTOOL_DATA_TIER",
    "PSYCHTOOL_API_KEY",
    "PSYCHTOOL_REDACT",
)


@pytest.fixture(autouse=True)
def _clear_psychtool_environment(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _workspace(tmp_path):
    workspace = init_workspace(tmp_path / "case-a", case_id="case-a")
    import_material(
        workspace, material_id="doc-1", title="Synthetic source",
        provider="synthetic", date="synthetic date", text="Synthetic observation.",
    )
    set_known_names(workspace, ["Jane Doe"])
    add_claim(
        workspace,
        claim_id="claim-1",
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="synthetic intake",
        record_time="synthetic date",
        category="client_statement",
        topic="history",
        text="Jane Doe called 312-555-0142 about sleep.",
    )
    return workspace


def _configure(monkeypatch, tmp_path, *, tier="real"):
    monkeypatch.setenv("PSYCHTOOL_WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setenv("PSYCHTOOL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("PSYCHTOOL_MODEL", "local-model")
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", tier)
    monkeypatch.setenv("PSYCHTOOL_API_KEY", "api-key-must-not-leak")


def _prepare_body():
    return {
        "template_id": "ew-report",
        "template_version": 1,
        "section_id": "background_information",
        "claim_ids": ["claim-1"],
        "instructions": "Write the background section.",
        "purpose": "section_generation",
    }


def _prepare(client):
    return client.post("/api/workspaces/case-a/egress/prepare", json=_prepare_body())


def test_prepare_returns_review_preview_without_calling_transport(tmp_path, monkeypatch):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path)
    calls = []
    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(
        app_module,
        "http_transport",
        lambda config, envelope: calls.append((config, envelope)),
    )

    response = _prepare(TestClient(create_app()))

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"]
    assert payload["status"] == "prepared"
    assert payload["content_hash"]
    assert payload["provider_base_url"] == "http://127.0.0.1:11434/v1"
    assert payload["model"] == "local-model"
    assert payload["source_refs"] == [
        {"kind": "claim", "id": "claim-1", "version": 1}
    ]
    assert {"name", "telephone"} <= set(payload["identifier_categories"])
    assert payload["requires_human_review"] is True
    assert "[[NAME_" in payload["preview"]
    assert "[[TELEPHONE_" in payload["preview"]
    assert "Jane Doe" not in payload["preview"]
    assert "312-555-0142" not in payload["preview"]
    assert calls == []


def test_human_approve_send_and_rebuilt_app_get_persisted_request(
    tmp_path, monkeypatch
):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path)
    calls = []

    def transport(config, envelope):
        calls.append((config, envelope))
        return "Keep [[NAME_1]] in first-version output."

    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(app_module, "http_transport", transport)
    client = TestClient(create_app())
    prepared_response = _prepare(client)
    assert prepared_response.status_code == 200
    prepared = prepared_response.json()
    request_path = f"/api/workspaces/case-a/egress/{prepared['request_id']}"

    unapproved = client.post(f"{request_path}/send")
    assert unapproved.status_code == 409
    assert calls == []

    approved = client.post(
        f"{request_path}/approve",
        json={
            "content_hash": prepared["content_hash"],
            "reviewer": "reviewer-1",
            "synthetic_auto_reason": None,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approval_mode"] == "human"

    sent = client.post(f"{request_path}/send")
    assert sent.status_code == 200
    assert sent.json()["text"] == "Keep [[NAME_1]] in first-version output."
    assert len(calls) == 1
    assert calls[0][1] == {
        "model": prepared["model"],
        "messages": [{"role": "user", "content": prepared["preview"]}],
    }

    rebuilt_client = TestClient(create_app())
    persisted = rebuilt_client.get(request_path)
    assert persisted.status_code == 200
    assert persisted.json()["request_id"] == prepared["request_id"]
    assert persisted.json()["status"] == "sent"
    assert persisted.json()["preview"] == prepared["preview"]

    duplicate = rebuilt_client.post(f"{request_path}/send")
    assert duplicate.status_code == 409
    assert len(calls) == 1


def test_synthetic_auto_approval_uses_server_config(tmp_path, monkeypatch):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path, tier="synthetic")
    client = TestClient(create_app())
    prepared = _prepare(client).json()
    request_path = f"/api/workspaces/case-a/egress/{prepared['request_id']}"

    response = client.post(
        f"{request_path}/approve",
        json={
            "content_hash": prepared["content_hash"],
            "synthetic_auto_reason": "synthetic fixture",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["approval_mode"] == "synthetic_auto"
    assert response.json()["approval_reason"] == "synthetic fixture"
    assert response.json()["reviewer"] is None


def test_synthetic_api_wrong_displayed_hash_rejects_approval_and_send(tmp_path, monkeypatch):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path, tier="synthetic")
    calls = []
    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(app_module, "http_transport", lambda config, envelope: calls.append(envelope))
    client = TestClient(create_app())
    prepared = _prepare(client).json()
    request_path = f"/api/workspaces/case-a/egress/{prepared['request_id']}"

    response = client.post(
        f"{request_path}/approve",
        json={"content_hash": "0" * 64, "synthetic_auto_reason": "synthetic fixture"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "egress approval rejected"}
    assert client.post(f"{request_path}/send").status_code == 409
    persisted = client.get(request_path).json()
    assert persisted["status"] == "invalidated"
    assert persisted["approval_mode"] is None
    assert calls == []


def test_approve_requires_exactly_one_approval_method(tmp_path, monkeypatch):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path)
    client = TestClient(create_app())
    prepared = _prepare(client).json()
    approve_path = (
        f"/api/workspaces/case-a/egress/{prepared['request_id']}/approve"
    )

    neither = client.post(
        approve_path,
        json={"content_hash": prepared["content_hash"]},
    )
    both = client.post(
        approve_path,
        json={
            "content_hash": prepared["content_hash"],
            "reviewer": "reviewer-1",
            "synthetic_auto_reason": "synthetic fixture",
        },
    )

    assert neither.status_code == 400
    assert both.status_code == 400


def test_safe_errors_do_not_echo_request_or_provider_secrets(tmp_path, monkeypatch):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path)
    client = TestClient(create_app())
    prepared = _prepare(client).json()
    approve_path = (
        f"/api/workspaces/case-a/egress/{prepared['request_id']}/approve"
    )

    rejected_auto = client.post(
        approve_path,
        json={
            "content_hash": prepared["content_hash"],
            "synthetic_auto_reason": "auto is unsafe for real data",
        },
    )
    assert rejected_auto.status_code == 400

    wrong_hash = client.post(
        approve_path,
        json={
            "content_hash": "wrong-content-hash",
            "reviewer": "reviewer-1",
        },
    )
    assert wrong_hash.status_code in {400, 409}

    invalid_payload = _prepare_body() | {"redact": "Jane Doe 312-555-0142"}
    invalid = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json=invalid_payload,
    )
    assert invalid.status_code == 400

    complete_prompt = prepared["preview"]
    for response in (rejected_auto, wrong_hash, invalid):
        encoded = json.dumps(response.json())
        assert "Jane Doe" not in encoded
        assert "312-555-0142" not in encoded
        assert complete_prompt not in encoded
        assert "api-key-must-not-leak" not in encoded
        assert "auto is unsafe for real data" not in encoded


@pytest.mark.parametrize("provider_body", [
    "Provider returned person@example.com and 312-555-9999.",
    "Jane Doe attended.",
])
def test_output_pii_is_blocked_without_echoing_provider_body(tmp_path, monkeypatch, provider_body):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path)
    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(
        app_module,
        "http_transport",
        lambda config, envelope: provider_body,
    )
    client = TestClient(create_app())
    prepared = _prepare(client).json()
    request_path = f"/api/workspaces/case-a/egress/{prepared['request_id']}"
    client.post(
        f"{request_path}/approve",
        json={
            "content_hash": prepared["content_hash"],
            "reviewer": "reviewer-1",
        },
    )

    response = client.post(f"{request_path}/send")

    assert response.status_code in {409, 422}
    encoded = json.dumps(response.json())
    assert provider_body not in encoded
    assert "person@example.com" not in encoded
    assert "312-555-9999" not in encoded
    assert "Jane Doe" not in encoded
    assert client.get(request_path).json()["status"] == "sent"


def test_prepare_rejects_caller_controlled_routing_fields(tmp_path, monkeypatch):
    _workspace(tmp_path)
    _configure(monkeypatch, tmp_path)
    body = _prepare_body() | {
        "provider_base_url": "https://attacker.invalid/v1",
        "model": "attacker-model",
        "source_refs": [],
    }

    response = TestClient(create_app()).post(
        "/api/workspaces/case-a/egress/prepare", json=body
    )

    assert response.status_code == 400
