"""Strict gateway tests for approved, immutable egress envelopes."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from psychtool.config import Config
from psychtool.core.claims import add_claim, get_claim
from psychtool.core.draft import build_draft_request_input
from psychtool.core.sections import build_section_request_input
from psychtool.core.egress import (
    EgressStaleError,
    EgressStateError,
    SourceRef,
    approve_human,
    approve_synthetic,
    canonical_hash,
    get_egress_request,
    invalidate_request,
    prepare_egress_request,
    save_egress_request,
)
from psychtool.core.workspace import import_material, init_workspace, set_known_names
from psychtool.gateway.client import (
    EgressOutputBlockedError,
    NetworkForbiddenError,
    send_approved,
)
from psychtool.gateway.http import http_transport


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


def _cfg(
    tier="synthetic",
    base_url="https://provider.invalid/v1",
    model="model-1",
):
    return Config(base_url=base_url, model=model, data_tier=tier, api_key="test-key")


def _prepare(workspace, *, config=None, source_refs=None):
    config = config or _cfg()
    return prepare_egress_request(
        workspace,
        prompt="Safe synthetic prompt.",
        purpose="draft_generation",
        config=config,
        source_refs=source_refs or [],
    )


def _approve(workspace, *, config=None, source_refs=None):
    request = _prepare(workspace, config=config, source_refs=source_refs)
    return approve_synthetic(
        workspace,
        request.request_id,
        reason="synthetic test fixture",
        content_hash=request.content_hash,
    )


class TransportSpy:
    def __init__(self, response="Clean generated text."):
        self.response = response
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, config, envelope):
        with self._lock:
            self.calls.append((config, envelope))
        return self.response


def test_send_approved_transports_exact_approved_envelope_once(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _cfg()
    approved = _approve(workspace, config=config)
    transport = TransportSpy()

    result = send_approved(
        workspace,
        approved.request_id,
        config=config,
        transport=transport,
    )

    assert result == "Clean generated text."
    assert transport.calls == [(config, approved.envelope.model_dump())]
    persisted = get_egress_request(workspace, approved.request_id)
    assert persisted.status == "sent"
    assert persisted.sent_at is not None


@pytest.mark.parametrize("status", ["prepared", "invalidated"])
def test_send_rejects_unapproved_request_before_transport(tmp_path, status):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare(workspace)
    if status == "invalidated":
        invalidate_request(workspace, request.request_id)
    transport = TransportSpy()

    with pytest.raises(EgressStateError):
        send_approved(
            workspace,
            request.request_id,
            config=_cfg(),
            transport=transport,
        )

    assert transport.calls == []


def test_second_send_is_rejected_before_transport(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    transport = TransportSpy()

    send_approved(workspace, approved.request_id, config=_cfg(), transport=transport)
    with pytest.raises(EgressStateError):
        send_approved(workspace, approved.request_id, config=_cfg(), transport=transport)

    assert len(transport.calls) == 1
    assert get_egress_request(workspace, approved.request_id).status == "sent"


@pytest.mark.parametrize(
    "config",
    [
        _cfg(model="other-model"),
        _cfg(base_url="https://other-provider.invalid/v1"),
        _cfg(tier="real"),
    ],
)
def test_send_rejects_config_mismatch_before_transport(tmp_path, config):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    transport = TransportSpy()

    with pytest.raises(EgressStateError):
        send_approved(
            workspace,
            approved.request_id,
            config=config,
            transport=transport,
        )

    assert transport.calls == []
    assert get_egress_request(workspace, approved.request_id).status == "approved"


def test_send_rejects_invalid_approval_mode_before_transport(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    save_egress_request(
        workspace,
        approved.model_copy(update={"approval_mode": None}),
    )
    transport = TransportSpy()

    with pytest.raises(EgressStateError):
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=transport,
        )

    assert transport.calls == []


def test_send_rejects_hash_mismatch_before_transport(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    tampered = approved.model_copy(deep=True)
    tampered.envelope.messages[0]["content"] = "Tampered after approval."
    assert canonical_hash(tampered) != tampered.content_hash
    save_egress_request(workspace, tampered)
    transport = TransportSpy()

    with pytest.raises(EgressStateError) as caught:
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=transport,
        )

    assert transport.calls == []
    assert "Tampered after approval." not in str(caught.value)


def _claim_fields(*, text="Synthetic observation."):
    return {
        "source_document_id": "material-1",
        "source_version": 1,
        "source_passage_id": "p001",
        "provider_role": "self_report",
        "observation_setting": "synthetic intake",
        "record_time": "synthetic date",
        "category": "client_statement",
        "topic": "history",
        "text": text,
    }


def test_send_invalidates_stale_sources_before_transport(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    claim = add_claim(workspace, claim_id="claim-1", **_claim_fields())
    approved = _approve(
        workspace,
        source_refs=[SourceRef(kind="claim", id=claim.id, version=claim.version)],
    )
    add_claim(
        workspace,
        claim_id=claim.id,
        **_claim_fields(text="Updated synthetic observation."),
    )
    transport = TransportSpy()

    with pytest.raises(EgressStaleError):
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=transport,
        )

    assert transport.calls == []
    assert get_egress_request(workspace, approved.request_id).status == "invalidated"


def test_real_request_refuses_external_endpoint_before_transport(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _cfg(tier="real")
    request = _prepare(workspace, config=config)
    from psychtool.core.egress import approve_human

    approved = approve_human(
        workspace,
        request.request_id,
        reviewer="reviewer-1",
        content_hash=request.content_hash,
    )
    transport = TransportSpy()

    with pytest.raises(NetworkForbiddenError):
        send_approved(
            workspace,
            approved.request_id,
            config=config,
            transport=transport,
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:11434/v1", "http://localhost:11434/v1"],
)
def test_real_request_allows_local_endpoint(tmp_path, base_url):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = _cfg(tier="real", base_url=base_url)
    request = _prepare(workspace, config=config)
    from psychtool.core.egress import approve_human

    approved = approve_human(
        workspace,
        request.request_id,
        reviewer="reviewer-1",
        content_hash=request.content_hash,
    )

    assert send_approved(
        workspace,
        approved.request_id,
        config=config,
        transport=TransportSpy(),
    ) == "Clean generated text."


def test_output_identifiers_are_blocked_after_request_is_marked_sent(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    telephone = "312-555-0142"
    email = "new.person@example.com"
    response = f"Call {telephone} or email {email}."
    transport = TransportSpy(response=response)

    with pytest.raises(EgressOutputBlockedError) as caught:
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=transport,
        )

    assert caught.value.categories == ("email", "telephone")
    assert caught.value.__dict__ == {"categories": ("email", "telephone")}
    assert telephone not in str(caught.value)
    assert email not in str(caught.value)
    assert response not in str(caught.value)
    assert len(transport.calls) == 1
    assert get_egress_request(workspace, approved.request_id).status == "sent"
    persisted = (
        workspace / "egress" / f"{approved.request_id}.json"
    ).read_text(encoding="utf-8")
    assert telephone not in persisted
    assert email not in persisted


def test_transport_exception_leaves_approved_and_retains_owned_send_lock(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    response_secret = "response-secret@example.com"

    def failing_transport(config, envelope):
        raise RuntimeError(f"provider exposed {response_secret}")

    with pytest.raises(RuntimeError) as caught:
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=failing_transport,
        )

    assert str(caught.value) == "model transport failed"
    assert response_secret not in str(caught.value)
    assert get_egress_request(workspace, approved.request_id).status == "approved"
    lock_path = workspace / "egress" / f"{approved.request_id}.send.lock"
    assert lock_path.exists()
    assert response_secret not in lock_path.read_text(encoding="ascii")


def test_post_transport_persistence_failure_retains_send_lock(tmp_path, monkeypatch):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    transport = TransportSpy()

    def fail_sent_persistence(workspace_arg, request_arg):
        assert request_arg.status == "sent"
        raise OSError("simulated persistence failure")

    monkeypatch.setattr(
        "psychtool.gateway.client.save_egress_request",
        fail_sent_persistence,
    )

    with pytest.raises(OSError):
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=transport,
        )

    assert len(transport.calls) == 1
    assert get_egress_request(workspace, approved.request_id).status == "approved"
    lock_path = workspace / "egress" / f"{approved.request_id}.send.lock"
    assert lock_path.exists()
    with pytest.raises(EgressStateError):
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=transport,
        )
    assert len(transport.calls) == 1


def test_existing_send_lock_fails_closed_without_removing_foreign_owner(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    lock_path = workspace / "egress" / f"{approved.request_id}.send.lock"
    lock_path.write_text("foreign-owner", encoding="ascii")
    transport = TransportSpy()

    with pytest.raises(EgressStateError):
        send_approved(
            workspace,
            approved.request_id,
            config=_cfg(),
            transport=transport,
        )

    assert transport.calls == []
    assert lock_path.read_text(encoding="ascii") == "foreign-owner"
    assert get_egress_request(workspace, approved.request_id).status == "approved"


def test_concurrent_senders_compete_for_one_send_lock(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    approved = _approve(workspace)
    start = threading.Barrier(3)
    transport_entered = threading.Event()
    release_transport = threading.Event()
    loser_finished = threading.Event()
    calls_lock = threading.Lock()
    call_count = 0
    successes = []
    failures = []

    def blocking_transport(config, envelope):
        nonlocal call_count
        with calls_lock:
            call_count += 1
        transport_entered.set()
        assert release_transport.wait(timeout=5)
        return "Clean generated text."

    def send():
        start.wait(timeout=5)
        try:
            successes.append(
                send_approved(
                    workspace,
                    approved.request_id,
                    config=_cfg(),
                    transport=blocking_transport,
                )
            )
        except Exception as error:  # captured for deterministic thread assertions
            failures.append(error)
            loser_finished.set()

    first = threading.Thread(target=send)
    second = threading.Thread(target=send)
    first.start()
    second.start()
    start.wait(timeout=5)
    assert transport_entered.wait(timeout=2)
    assert loser_finished.wait(timeout=2)
    release_transport.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert successes == ["Clean generated text."]
    assert len(failures) == 1
    assert isinstance(failures[0], EgressStateError)
    assert call_count == 1
    assert get_egress_request(workspace, approved.request_id).status == "sent"


@pytest.mark.parametrize("builder", ["draft", "section"])
def test_builder_request_invalidates_when_claim_material_is_reimported(tmp_path, builder):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    material_fields = dict(
        material_id="material-1", title="Synthetic material",
        provider="synthetic provider", date="synthetic date",
        text="Synthetic source passage.",
    )
    import_material(workspace, **material_fields)
    claim = add_claim(workspace, claim_id="claim-1", **_claim_fields())
    args = dict(claim_ids=[claim.id], instructions="Use the synthetic source.")
    if builder == "draft":
        prompt, refs = build_draft_request_input(workspace, **args)
    else:
        prompt, refs = build_section_request_input(
            workspace, template_id="ew-report", template_version=1,
            section_id="background_information", **args,
        )
    config = _cfg(tier="real", base_url="http://127.0.0.1:11434/v1")
    request = prepare_egress_request(
        workspace, prompt=prompt, source_refs=refs, config=config,
        purpose=f"{builder}_generation",
    )
    approve_human(
        workspace, request.request_id, reviewer="reviewer-1",
        content_hash=request.content_hash,
    )
    assert import_material(workspace, **material_fields).version == 2
    assert get_claim(workspace, claim.id).version == 1
    transport = TransportSpy()

    with pytest.raises(EgressStaleError, match="^egress source reference is stale$"):
        send_approved(workspace, request.request_id, config=config, transport=transport)

    assert transport.calls == []
    assert get_egress_request(workspace, request.request_id).status == "invalidated"


@pytest.mark.parametrize("response_body", [b"not-json", b"{}"])
def test_received_http_post_with_unusable_response_cannot_be_retried(tmp_path, response_body):
    deliveries = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            deliveries.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
        config = _cfg(base_url=f"http://127.0.0.1:{server.server_port}/v1")
        approved = _approve(workspace, config=config)
        with pytest.raises(RuntimeError, match="^model transport failed$"):
            send_approved(workspace, approved.request_id, config=config, transport=http_transport)
        with pytest.raises(EgressStateError, match="^egress request send is locked$"):
            send_approved(workspace, approved.request_id, config=config, transport=http_transport)
        assert deliveries == [approved.envelope.model_dump()]
        assert get_egress_request(workspace, approved.request_id).status == "approved"
        lock = workspace / "egress" / f"{approved.request_id}.send.lock"
        assert len(lock.read_text(encoding="ascii")) == 64
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_known_name_only_output_is_blocked_and_not_persisted(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    known_name = "Mira Quenby"
    set_known_names(workspace, [known_name])
    approved = _approve(workspace)
    transport = TransportSpy(response=f"{known_name} attended.")

    with pytest.raises(EgressOutputBlockedError) as caught:
        send_approved(workspace, approved.request_id, config=_cfg(), transport=transport)

    assert caught.value.__dict__ == {"categories": ("name",)}
    assert str(caught.value) == "egress output blocked; identifier categories: name"
    assert len(transport.calls) == 1
    assert get_egress_request(workspace, approved.request_id).status == "sent"
    assert all(known_name not in path.read_text(encoding="utf-8")
               for path in (workspace / "egress").iterdir())


def test_http_transport_sends_envelope_as_exact_json_body(monkeypatch):
    envelope = {
        "model": "approved-model",
        "messages": [
            {"role": "system", "content": "Approved system content."},
            {"role": "user", "content": "Approved user content."},
        ],
        "temperature": 0,
    }
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "Clean response."}}]}
            ).encode("utf-8")

    class FakeOpener:
        def open(self, request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(
        "psychtool.gateway.http.urllib.request.build_opener",
        lambda *handlers: FakeOpener(),
    )
    config = _cfg(model="runtime-model")

    assert http_transport(config, envelope) == "Clean response."
    request = captured["request"]
    assert request.full_url == "https://provider.invalid/v1/chat/completions"
    assert json.loads(request.data.decode("utf-8")) == envelope
    assert request.headers["Authorization"] == "Bearer test-key"
