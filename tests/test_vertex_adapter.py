"""PT-13 (GROK-43 / R11): Vertex adapter, AI Studio refusal, real-profile egress."""

from __future__ import annotations

import json
import socket
import urllib.request

import pytest

from psychtool.config import Config, load_config
from psychtool.core.egress import (
    EgressStateError,
    approve_human,
    approve_synthetic,
    canonical_hash,
    get_egress_request,
    prepare_egress_request,
    save_egress_request,
)
from psychtool.core.workspace import init_workspace, set_known_names
from psychtool.gateway.client import (
    EgressOutputBlockedError,
    NetworkForbiddenError,
    send_approved,
)
from psychtool.gateway.endpoints import (
    AIStudioForbiddenError,
    VertexAuthError,
    VertexConfigError,
    is_ai_studio_endpoint,
    is_vertex_endpoint,
    vertex_openapi_base_url,
)
from psychtool.gateway.http import http_transport
from psychtool.gateway.select import select_transport
from psychtool.gateway.vertex import vertex_transport

VERTEX_URL = vertex_openapi_base_url("synthetic-proj", "us-central1")
AISTUDIO_URLS = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
    "https://generativelanguage.google.com/v1beta/models/gemini-flash",
    "https://ai.google.dev/v1",
    "https://aistudio.google.com/",
    "https://aistudio.google.cn/",
    "https://example.invalid/v1beta/models/gemini-pro",
)

_ENV_VARS = (
    "PSYCHTOOL_BASE_URL",
    "PSYCHTOOL_MODEL",
    "PSYCHTOOL_JUDGE_MODEL",
    "PSYCHTOOL_DATA_TIER",
    "PSYCHTOOL_API_KEY",
    "PSYCHTOOL_REDACT",
    "PSYCHTOOL_TRANSPORT",
    "PSYCHTOOL_PROFILE",
    "PSYCHTOOL_VERTEX_PROJECT",
    "PSYCHTOOL_VERTEX_LOCATION",
    "PSYCHTOOL_VERTEX_ACCESS_TOKEN",
)


@pytest.fixture(autouse=True)
def _clear_psychtool_environment(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def install_egress_guard(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in this test")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def _vertex_config(**kwargs) -> Config:
    values = dict(
        base_url=VERTEX_URL,
        model="gemini-2.0-flash",
        data_tier="synthetic",
        transport="vertex",
        profile="vertex",
        vertex_project="synthetic-proj",
        vertex_location="us-central1",
    )
    values.update(kwargs)
    return Config(**values)


def _prepare(workspace, *, config):
    return prepare_egress_request(
        workspace,
        prompt="Safe synthetic prompt about a timed reading exercise.",
        purpose="draft_generation",
        config=config,
        source_refs=[],
    )


def _approve(workspace, *, config):
    request = _prepare(workspace, config=config)
    if config.data_tier == "real":
        return approve_human(
            workspace,
            request.request_id,
            reviewer="reviewer-1",
            content_hash=request.content_hash,
        )
    return approve_synthetic(
        workspace,
        request.request_id,
        reason="synthetic test fixture",
        content_hash=request.content_hash,
    )


class TransportSpy:
    def __init__(self, response="Clean generated text.", error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, config, envelope):
        self.calls.append((config, envelope))
        if self.error is not None:
            raise self.error
        return self.response


class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, content="Synthetic Vertex reply."):
        self.content = content
        self.requests: list = []

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        body = json.dumps({"choices": [{"message": {"content": self.content}}]})
        return _FakeResponse(body)


def _install_fake_opener(monkeypatch, opener: _FakeOpener):
    monkeypatch.setattr(
        "psychtool.gateway.vertex.urllib.request.build_opener",
        lambda *args, **kwargs: opener,
    )


def test_vertex_openapi_url_shape():
    assert VERTEX_URL == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/synthetic-proj"
        "/locations/us-central1/endpoints/openapi"
    )
    assert is_vertex_endpoint(VERTEX_URL)
    assert not is_ai_studio_endpoint(VERTEX_URL)


def test_profile_vertex_builds_base_url_and_selects_transport(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_PROFILE", "vertex")
    monkeypatch.setenv("PSYCHTOOL_VERTEX_PROJECT", "synthetic-proj")
    monkeypatch.setenv("PSYCHTOOL_VERTEX_LOCATION", "us-central1")
    monkeypatch.setenv("PSYCHTOOL_MODEL", "gemini-2.0-flash")
    cfg = load_config()
    assert cfg.profile == "vertex"
    assert cfg.transport == "vertex"
    assert cfg.data_tier == "synthetic"
    assert cfg.base_url == VERTEX_URL
    assert select_transport(cfg) is vertex_transport


def test_profile_real_forces_data_tier_real(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_PROFILE", "real")
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "synthetic")
    cfg = load_config()
    assert cfg.profile == "real"
    assert cfg.data_tier == "real"


def test_profile_defaults_to_fake():
    cfg = load_config()
    assert cfg.profile == "fake"
    assert cfg.transport == "fake"
    assert cfg.data_tier == "synthetic"


def test_vertex_transport_posts_envelope_with_injected_token(monkeypatch):
    install_egress_guard(monkeypatch)
    opener = _FakeOpener()
    _install_fake_opener(monkeypatch, opener)
    config = _vertex_config()
    envelope = {"model": "gemini-2.0-flash", "messages": [{"role": "user", "content": "hello"}]}

    text = vertex_transport(config, envelope, token_provider=lambda: "test-token")

    assert text == "Synthetic Vertex reply."
    assert len(opener.requests) == 1
    req, timeout = opener.requests[0]
    assert timeout == 120
    assert req.full_url == VERTEX_URL + "/chat/completions"
    assert req.get_header("Authorization") == "Bearer test-token"
    assert json.loads(req.data.decode("utf-8")) == envelope


def test_vertex_transport_without_token_fails_closed_and_does_not_probe(monkeypatch):
    install_egress_guard(monkeypatch)
    opener = _FakeOpener()
    _install_fake_opener(monkeypatch, opener)
    with pytest.raises(VertexAuthError, match="are not probed"):
        vertex_transport(_vertex_config(), {"model": "gemini-2.0-flash", "messages": []})
    assert opener.requests == []


@pytest.mark.parametrize("url", AISTUDIO_URLS)
def test_vertex_and_http_refuse_ai_studio_urls(url, monkeypatch):
    install_egress_guard(monkeypatch)
    opener = _FakeOpener()
    _install_fake_opener(monkeypatch, opener)
    monkeypatch.setattr(
        "psychtool.gateway.http.urllib.request.build_opener",
        lambda *args, **kwargs: opener,
    )
    vertex_cfg = _vertex_config(base_url=url)
    http_cfg = Config(base_url=url, model="gemini-pro", transport="http")
    envelope = {"model": "gemini-pro", "messages": []}
    with pytest.raises(AIStudioForbiddenError):
        vertex_transport(vertex_cfg, envelope, token_provider=lambda: "test-token")
    with pytest.raises(AIStudioForbiddenError):
        http_transport(http_cfg, envelope)
    assert opener.requests == []


def test_vertex_transport_rejects_non_vertex_url(monkeypatch):
    install_egress_guard(monkeypatch)
    with pytest.raises(VertexConfigError):
        vertex_transport(
            _vertex_config(base_url="https://provider.invalid/v1"),
            {"model": "x", "messages": []},
            token_provider=lambda: "test-token",
        )


def test_real_profile_refuses_vertex_endpoint_with_no_network(tmp_path, monkeypatch):
    install_egress_guard(monkeypatch)
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _vertex_config(data_tier="real", profile="real")
    approved = _approve(workspace, config=config)
    transport = TransportSpy()

    with pytest.raises(NetworkForbiddenError, match="data_tier='real'"):
        send_approved(
            workspace,
            approved.request_id,
            config=config,
            transport=transport,
        )

    assert transport.calls == []
    assert get_egress_request(workspace, approved.request_id).status == "approved"


def test_hash_binding_refuses_send_after_approval_change(tmp_path, monkeypatch):
    install_egress_guard(monkeypatch)
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _vertex_config()
    approved = _approve(workspace, config=config)
    tampered = approved.model_copy(
        update={
            "envelope": approved.envelope.model_copy(
                update={
                    "messages": [
                        {"role": "user", "content": "Changed after approval."}
                    ]
                }
            )
        }
    )
    assert canonical_hash(tampered) != tampered.content_hash
    save_egress_request(workspace, tampered)
    transport = TransportSpy()

    with pytest.raises(EgressStateError, match="content hash does not match"):
        send_approved(
            workspace,
            approved.request_id,
            config=config,
            transport=transport,
        )

    assert transport.calls == []


def test_successful_send_cannot_be_resent(tmp_path, monkeypatch):
    install_egress_guard(monkeypatch)
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _vertex_config()
    approved = _approve(workspace, config=config)
    transport = TransportSpy()

    assert (
        send_approved(
            workspace, approved.request_id, config=config, transport=transport
        )
        == "Clean generated text."
    )
    with pytest.raises(EgressStateError):
        send_approved(
            workspace, approved.request_id, config=config, transport=transport
        )
    assert len(transport.calls) == 1


def test_output_blocked_request_cannot_be_resent(tmp_path, monkeypatch):
    install_egress_guard(monkeypatch)
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _vertex_config()
    approved = _approve(workspace, config=config)
    transport = TransportSpy(response="Call 312-555-0142 please.")

    with pytest.raises(EgressOutputBlockedError):
        send_approved(
            workspace, approved.request_id, config=config, transport=transport
        )
    with pytest.raises(EgressStateError):
        send_approved(
            workspace, approved.request_id, config=config, transport=transport
        )
    assert len(transport.calls) == 1
    assert get_egress_request(workspace, approved.request_id).status == "sent"


def test_uncertain_transport_failure_cannot_be_resent(tmp_path, monkeypatch):
    install_egress_guard(monkeypatch)
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _vertex_config()
    approved = _approve(workspace, config=config)
    transport = TransportSpy(error=RuntimeError("socket timed out"))

    with pytest.raises(RuntimeError, match="model transport failed"):
        send_approved(
            workspace, approved.request_id, config=config, transport=transport
        )
    with pytest.raises(EgressStateError, match="send is locked"):
        send_approved(
            workspace, approved.request_id, config=config, transport=transport
        )
    assert len(transport.calls) == 1
    assert get_egress_request(workspace, approved.request_id).status == "approved"


def test_deidentified_preview_hides_known_name(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    set_known_names(workspace, ["Alex Rivera"])
    config = Config(base_url="https://provider.invalid/v1", model="model-1")
    request = prepare_egress_request(
        workspace,
        prompt="Alex Rivera completed a synthetic timed reading exercise.",
        purpose="draft_generation",
        config=config,
        source_refs=[],
    )
    preview = request.envelope.messages[0]["content"]
    assert "Alex Rivera" not in preview
    assert "[[NAME_" in preview
    assert "name" in request.identifier_categories
