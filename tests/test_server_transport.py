"""The default server send path uses the offline fake transport only.

The full prepare -> approve -> send flow is exercised over HTTP with every
socket creation blocked, proving the default dev run cannot touch the network.
The real ``http_transport`` is reachable only through the explicit
``PSYCHTOOL_TRANSPORT=http`` opt-in.
"""

import socket

import pytest
from fastapi.testclient import TestClient

from psychtool.config import load_config
from psychtool.gateway.fake import FAKE_UNSOURCED_SENTENCE, fake_transport
from psychtool.gateway.http import http_transport
from psychtool.server.app import _select_transport, create_app
from tests.conftest import build_client

_ENV_VARS = (
    "PSYCHTOOL_BASE_URL",
    "PSYCHTOOL_MODEL",
    "PSYCHTOOL_JUDGE_MODEL",
    "PSYCHTOOL_DATA_TIER",
    "PSYCHTOOL_API_KEY",
    "PSYCHTOOL_REDACT",
    "PSYCHTOOL_TRANSPORT",
)


@pytest.fixture(autouse=True)
def _clear_psychtool_environment(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _block_network(monkeypatch):
    """Forbid any outbound connection; in-process sockets (TestClient) still work."""

    def _forbidden(self, address):
        raise AssertionError(f"network access attempted: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("network access attempted")
    ))


def _prepared_approved(client):
    assert client.post("/api/workspaces", json={"case_id": "case-a"}).status_code == 201
    pasted = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "doc-1",
            "title": "Synthetic source",
            "provider": "synthetic",
            "date": "2026-11-20",
            "text": "Synthetic observation paragraph.",
            "synthetic_confirmed": True,
        },
    )
    assert pasted.status_code == 200
    suggestions = client.get(
        "/api/workspaces/case-a/materials/doc-1/suggestions",
        params={"provider_role": "self_report"},
    ).json()
    assert len(suggestions) == 1
    assert client.post("/api/workspaces/case-a/claims", json=suggestions[0]).status_code == 200

    prepared = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": "history",
            "claim_ids": [suggestions[0]["id"]],
            "instructions": "Write the history section from the accepted claim.",
            "purpose": "section_generation",
        },
    )
    assert prepared.status_code == 200
    prepared = prepared.json()
    approved = client.post(
        f"/api/workspaces/case-a/egress/{prepared['request_id']}/approve",
        json={
            "content_hash": prepared["content_hash"],
            "reviewer": "e2e-reviewer",
            "synthetic_auto_reason": None,
        },
    )
    assert approved.status_code == 200
    return prepared


def test_default_send_path_uses_fake_transport_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    _block_network(monkeypatch)
    client = build_client(create_app())
    prepared = _prepared_approved(client)

    sent = client.post(f"/api/workspaces/case-a/egress/{prepared['request_id']}/send")

    assert sent.status_code == 200
    body = sent.json()
    assert body["request_id"] == prepared["request_id"]
    assert body["status"] == "sent"
    text = body["text"]
    assert "FAKE OFFLINE RESPONSE" in text
    assert "Synthetic observation paragraph." in text
    assert FAKE_UNSOURCED_SENTENCE in text
    # The sent request persists exactly like a real send and stays send-once.
    persisted = client.get(f"/api/workspaces/case-a/egress/{prepared['request_id']}").json()
    assert persisted["status"] == "sent"
    assert client.post(f"/api/workspaces/case-a/egress/{prepared['request_id']}/send").status_code == 409


def test_transport_defaults_to_fake():
    assert load_config().transport == "fake"
    assert _select_transport(load_config()) is fake_transport


def test_http_transport_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_TRANSPORT", "http")
    assert load_config().transport == "http"
    assert _select_transport(load_config()) is http_transport


def test_unknown_transport_value_falls_back_to_fake(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_TRANSPORT", "carrier-pigeon")
    config = load_config()
    assert config.transport == "fake"
    assert _select_transport(config) is fake_transport


def test_saved_section_survives_reopen(tmp_path, monkeypatch):
    """Reloading the case (a fresh app) returns the saved section text."""
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    client = build_client(create_app())
    prepared = _prepared_approved(client)
    sent = client.post(f"/api/workspaces/case-a/egress/{prepared['request_id']}/send")
    text = sent.json()["text"]

    saved = client.put(
        "/api/workspaces/case-a/sections/history",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": text,
            "claim_ids": [r["id"] for r in prepared["source_refs"]],
            "status": "draft",
            "reviewer": None,
        },
    )
    assert saved.status_code == 200

    reopened = build_client(create_app())
    sections = reopened.get(
        "/api/workspaces/case-a/sections", params={"template_id": "intake-report"}
    ).json()
    history = next(s for s in sections if s["section_id"] == "history")
    assert history["text"] == text
    assert history["status"] == "draft"
    assert history["version"] == 1
    assert [m["id"] for m in reopened.get("/api/workspaces/case-a/materials").json()] == ["doc-1"]
    assert len(reopened.get("/api/workspaces/case-a/claims").json()) == 1
