"""Model-egress request hashing and persistence."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

import pytest

import psychtool.core.egress as egress_module

from psychtool.config import Config
from psychtool.core.claims import add_claim
from psychtool.core.draft import (
    build_draft_request_input,
    freeze_draft_input,
    persist_generated_draft,
)
from psychtool.core.egress import (
    EgressApprovalError,
    EgressBlockedError,
    EgressRequest,
    EgressStaleError,
    EgressStateError,
    OutboundEnvelope,
    SourceRef,
    approve_human,
    approve_synthetic,
    canonical_hash,
    get_egress_request,
    invalidate_request,
    prepare_egress_request,
    save_egress_request,
    serialize_egress_event,
)
from psychtool.core.review import validate_request_sources, validate_source_refs
from psychtool.gateway.client import send_approved
from psychtool.core.workspace import import_material, init_workspace, set_known_names


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


def make_request(**updates) -> EgressRequest:
    values = {
        "request_id": "egress-001",
        "workspace_id": "case-a",
        "purpose": "section_generation",
        "data_tier": "synthetic",
        "provider_base_url": "https://provider.invalid/v1",
        "envelope": OutboundEnvelope(
            model="m1",
            messages=[
                {"role": "system", "content": "Use only cited sources."},
                {"role": "user", "content": "Draft the history section."},
            ],
        ),
        "source_refs": [SourceRef(kind="claim", id="claim-1", version=2)],
        "identifier_categories": ["name", "date"],
        "content_hash": "sha256-placeholder",
        "status": "prepared",
        "approval_mode": None,
        "reviewer": None,
        "approval_reason": None,
        "prepared_at": "2026-11-08T20:00:00+00:00",
        "approved_at": None,
        "sent_at": None,
    }
    values.update(updates)
    return EgressRequest(**values)


def with_envelope(request: EgressRequest, **updates) -> EgressRequest:
    envelope = request.envelope.model_copy(update=updates, deep=True)
    return request.model_copy(update={"envelope": envelope}, deep=True)


@pytest.fixture
def unsafe_request_ids(tmp_path):
    return (
        "../escape",
        "..\\escape",
        str((tmp_path / "absolute-escape").resolve()),
        ".",
        "..",
        "",
    )


def test_request_model_rejects_unsafe_request_ids(unsafe_request_ids):
    for request_id in unsafe_request_ids:
        with pytest.raises(ValueError):
            make_request(request_id=request_id)


def test_save_rejects_unsafe_request_ids(tmp_path, unsafe_request_ids):
    request = make_request()
    for request_id in unsafe_request_ids:
        unvalidated = request.model_copy(update={"request_id": request_id})
        with pytest.raises(ValueError):
            save_egress_request(tmp_path, unvalidated)


def test_get_rejects_unsafe_request_ids(tmp_path, unsafe_request_ids):
    for request_id in unsafe_request_ids:
        with pytest.raises(ValueError):
            get_egress_request(tmp_path, request_id)


def test_hash_changes_when_actual_envelope_or_routing_changes():
    base = make_request()
    assert canonical_hash(base) == canonical_hash(base.model_copy(deep=True))
    assert canonical_hash(base) != canonical_hash(
        with_envelope(
            base,
            messages=[{"role": "user", "content": "changed"}],
        )
    )
    assert canonical_hash(base) != canonical_hash(with_envelope(base, model="m2"))
    assert canonical_hash(base) != canonical_hash(
        base.model_copy(update={"provider_base_url": "https://other.invalid/v1"})
    )


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("purpose", "judge"),
        ("source_refs", [SourceRef(kind="draft", id="draft-2", version=1)]),
        ("identifier_categories", ["email"]),
        ("data_tier", "real"),
    ],
)
def test_hash_includes_approval_relevant_content(field, changed):
    request = make_request()
    assert canonical_hash(request) != canonical_hash(
        request.model_copy(update={field: changed}, deep=True)
    )


def test_hash_excludes_lifecycle_metadata():
    request = make_request()
    changed = request.model_copy(
        update={
            "content_hash": "different-stored-hash",
            "status": "sent",
            "approval_mode": "human",
            "reviewer": "reviewer-1",
            "approval_reason": "lifecycle metadata",
            "prepared_at": "2026-11-09T01:00:00+00:00",
            "approved_at": "2026-11-09T01:01:00+00:00",
            "sent_at": "2026-11-09T01:02:00+00:00",
        }
    )
    assert canonical_hash(request) == canonical_hash(changed)
    assert canonical_hash(request) == canonical_hash(request.model_dump())


def test_request_roundtrip_does_not_persist_token_map(tmp_path):
    request = make_request()
    path = save_egress_request(tmp_path, request)
    loaded = get_egress_request(tmp_path, request.request_id)

    assert path == tmp_path / "egress" / "egress-001.json"
    assert loaded == request
    assert "token_map" not in loaded.model_dump()
    assert "token_map" not in path.read_text(encoding="utf-8")


def test_request_fields_are_json_serializable_without_api_key():
    request = make_request(
        status="approved",
        approval_mode="human",
        reviewer="reviewer-1",
        approved_at="2026-11-08T20:05:00+00:00",
        sent_at="2026-11-08T20:06:00+00:00",
    )
    dumped = request.model_dump(mode="json")
    encoded = json.dumps(dumped)

    assert request.request_id in encoded
    assert request.workspace_id in encoded
    assert request.purpose in encoded
    assert request.data_tier in encoded
    assert request.provider_base_url in encoded
    assert request.envelope.messages == dumped["envelope"]["messages"]
    assert request.source_refs[0].model_dump() in dumped["source_refs"]
    assert request.status in encoded
    assert request.approval_mode in encoded
    assert request.prepared_at in encoded
    assert request.approved_at in encoded
    assert request.sent_at in encoded
    assert "api_key" not in dumped


def test_egress_event_serialization_allowlists_safe_metadata():
    secrets = {
        "known_name": "Known Name",
        "phone": "312-555-0142",
        "response_body": "Sensitive provider response body.",
        "token_map": '{"[[NAME_1]]": "Known Name"}',
        "api_key": "sk-secret-api-key",
    }
    request = make_request(
        envelope=OutboundEnvelope(
            model="model-safe-name",
            messages=[
                {"role": "user", "content": " ".join(secrets.values())},
            ],
        ),
        identifier_categories=["name", "age_over_89", "vin", "zip"],
        content_hash="a" * 64,
        status="sent",
        approval_mode="human",
        reviewer="reviewer-1",
        approved_at="2026-11-08T20:05:00+00:00",
        sent_at="2026-11-08T20:06:00+00:00",
    )
    allowed_keys = {
        "event",
        "request_id",
        "content_hash",
        "purpose",
        "data_tier",
        "provider",
        "model",
        "identifier_categories",
        "status",
        "reviewer_fingerprint",
        "prepared_at",
        "approved_at",
        "sent_at",
        "timestamp",
        "error_category",
    }

    for event in ("prepared", "approved", "invalidated", "sent"):
        serialized = serialize_egress_event(request, event=event)
        assert set(serialized) <= allowed_keys
        assert serialized["event"] == event
        assert serialized["request_id"] == request.request_id
        assert serialized["content_hash"] == request.content_hash
        assert serialized["provider"] == "provider.invalid"
        encoded = json.dumps(serialized)
        assert all(secret not in encoded for secret in secrets.values())
        assert "messages" not in encoded
        assert "source_refs" not in encoded
        assert "approval_reason" not in encoded

    transport_error = serialize_egress_event(
        request,
        event="transport_error",
        timestamp="2026-11-08T20:07:00+00:00",
        error_category="transport_error",
    )
    assert set(transport_error) <= allowed_keys
    assert transport_error["error_category"] == "transport_error"
    assert transport_error["timestamp"] == "2026-11-08T20:07:00+00:00"
    encoded = json.dumps(transport_error)
    assert all(secret not in encoded for secret in secrets.values())

    with pytest.raises(ValueError, match="^invalid egress event metadata$"):
        serialize_egress_event(
            request,
            event="transport_error",
            error_category="provider said Sensitive provider response body.",
        )


@pytest.mark.parametrize(
    ("field", "polluted_value"),
    [
        ("identifier_categories", ["name", "Known Name"]),
        ("content_hash", '{"[[NAME_1]]": "Known Name"}'),
        ("content_hash", "A" * 64),
        ("prepared_at", "Sensitive provider response body."),
        ("approved_at", "Sensitive provider response body."),
        ("sent_at", "Sensitive provider response body."),
    ],
)
def test_egress_event_serialization_rejects_polluted_request_metadata(
    field, polluted_value
):
    request = make_request(
        identifier_categories=["name", "age_over_89", "vin", "zip"],
        content_hash="a" * 64,
        approved_at="2026-11-08T20:05:00+00:00",
        sent_at="2026-11-08T20:06:00+00:00",
    ).model_copy(update={field: polluted_value})

    with pytest.raises(ValueError) as caught:
        serialize_egress_event(request, event="sent")

    assert str(caught.value) == "invalid egress event metadata"
    assert str(polluted_value) not in str(caught.value)


@pytest.mark.parametrize(
    "timestamp",
    [
        "sk-secret-api-key",
        "2026-11-08T20:07:00",
    ],
)
def test_egress_event_serialization_rejects_unsafe_event_timestamp(timestamp):
    request = make_request(
        identifier_categories=["name"],
        content_hash="a" * 64,
    )

    with pytest.raises(ValueError) as caught:
        serialize_egress_event(
            request,
            event="transport_error",
            timestamp=timestamp,
            error_category="transport_error",
        )

    assert str(caught.value) == "invalid egress event metadata"
    assert timestamp not in str(caught.value)


def test_human_approval_event_fingerprints_untrusted_reviewer_from_record(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace)
    reviewer = 'Prompt: private narrative; {"[[NAME_1]]": "Mira Quenby"}; sk-secret-key'
    approve_human(
        workspace, request.request_id, reviewer=f"  {reviewer}  ",
        content_hash=request.content_hash,
    )
    record = get_egress_request(workspace, request.request_id)
    assert record.reviewer == reviewer
    for event in ("prepared", "approved", "invalidated", "sent", "transport_error"):
        metadata = serialize_egress_event(
            record, event=event,
            error_category="transport_error" if event == "transport_error" else None,
        )
        assert "reviewer" not in metadata
        fingerprint = metadata["reviewer_fingerprint"]
        assert re.fullmatch(r"[0-9a-f]{64}", fingerprint)
        assert fingerprint == hashlib.sha256(record.reviewer.encode("utf-8")).hexdigest()
        encoded = json.dumps(metadata)
        for secret in (reviewer, "private narrative", "[[NAME_1]]", "Mira Quenby", "sk-secret-key"):
            assert secret not in encoded
    with pytest.raises(ValueError, match="^invalid egress event metadata$") as caught:
        serialize_egress_event(record, event="approved", timestamp=reviewer)
    assert reviewer not in str(caught.value)
    assert serialize_egress_event(request, event="prepared")["reviewer_fingerprint"] is None


@pytest.mark.parametrize("unlink_error", [PermissionError, OSError])
def test_transition_unlink_failure_releases_mutex_and_keeps_file_lock(
    tmp_path, monkeypatch, unlink_error
):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")
    lock = egress_module._transition_lock_path(workspace, request.request_id)
    original_unlink = Path.unlink

    def fail_lock_unlink(path, *args, **kwargs):
        if path == lock:
            raise unlink_error(f"sensitive-path: {path}")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock_unlink)
    with pytest.raises(Exception) as cleanup_error:
        approve_human(
            workspace, request.request_id, reviewer="reviewer-1",
            content_hash=request.content_hash,
        )
    assert lock.exists()
    calls, send_errors = [], []

    def send():
        try:
            send_approved(
                workspace, request.request_id,
                config=Config(base_url="https://provider.invalid/v1", model="model-1"),
                transport=lambda config, envelope: calls.append(envelope) or "Clean output.",
            )
        except Exception as error:
            send_errors.append(error)

    thread = threading.Thread(target=send, daemon=True)
    thread.start()
    thread.join(timeout=1)
    assert not thread.is_alive(), "transition mutex remained held after unlink failed"
    assert isinstance(cleanup_error.value, EgressStateError)
    assert str(cleanup_error.value) == "egress request transition cleanup failed"
    assert len(send_errors) == 1
    assert isinstance(send_errors[0], EgressStateError)
    assert str(send_errors[0]) == "egress request transition is locked"
    assert lock.exists()
    assert re.fullmatch(r"[0-9a-f]{64}", lock.read_text(encoding="ascii"))
    assert calls == []


@pytest.mark.parametrize("mismatch", ["caller_hash", "canonical_hash"])
def test_synthetic_approval_binds_caller_and_canonical_hash_under_lock(
    tmp_path, monkeypatch, mismatch
):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")
    caller_hash = request.content_hash
    if mismatch == "caller_hash":
        caller_hash = "0" * 64
    else:
        changed = request.model_copy(deep=True)
        changed.envelope.messages[0]["content"] = "Changed synthetic content."
        save_egress_request(workspace, changed)
    lock = egress_module._transition_lock_path(workspace, request.request_id)
    original_compare = egress_module.secrets.compare_digest
    comparisons = []

    def compare_under_lock(first, second):
        assert lock.exists()
        comparisons.append((first, second))
        return original_compare(first, second)

    monkeypatch.setattr(egress_module.secrets, "compare_digest", compare_under_lock)
    with pytest.raises(EgressApprovalError, match="^egress content hash does not match$"):
        approve_synthetic(
            workspace, request.request_id, reason="synthetic fixture",
            content_hash=caller_hash,
        )
    assert comparisons == [(caller_hash, request.content_hash)]
    record = get_egress_request(workspace, request.request_id)
    assert record.status == "invalidated"
    assert record.approval_mode is None
    assert record.approved_at is None


def test_new_and_existing_workspaces_get_egress_directory(tmp_path):
    workspace = init_workspace(tmp_path / "new-workspace", case_id="case-a")
    assert (workspace / "egress").is_dir()

    old_workspace = tmp_path / "old-workspace"
    old_workspace.mkdir()
    request = make_request()
    save_egress_request(old_workspace, request)
    assert get_egress_request(old_workspace, request.request_id) == request


@pytest.mark.parametrize(
    ("location", "secrets", "categories"),
    [
        (
            "claim_text",
            ("Jane Doe", "312-555-0142"),
            {"name", "telephone"},
        ),
        (
            "instructions",
            ("evaluator@example.com",),
            {"email"},
        ),
        (
            "claim_metadata",
            ("Chicago, IL", "2026-10-01", "MRN: AB-1234"),
            {"geographic_subdivision", "date", "medical_record_number"},
        ),
    ],
)
def test_prepare_scans_and_redacts_the_complete_prompt(
    tmp_path, location, secrets, categories
):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    set_known_names(workspace, ["Jane Doe"])
    claim_fields = {
        "source_document_id": "doc-1",
        "source_version": 1,
        "source_passage_id": "p001",
        "provider_role": "self_report",
        "observation_setting": "intake",
        "record_time": "year 2026",
        "category": "client_statement",
        "topic": "history",
        "text": "No identifiers here.",
    }
    instructions = "Write a draft."
    if location == "claim_text":
        claim_fields["text"] = "Jane Doe called 312-555-0142."
    elif location == "instructions":
        instructions = "Send the result to evaluator@example.com."
    else:
        claim_fields.update(
            source_document_id="MRN: AB-1234",
            observation_setting="Chicago, IL",
            record_time="2026-10-01",
        )
    claim = add_claim(workspace, claim_id="claim-1", **claim_fields)
    prompt, source_refs = build_draft_request_input(
        workspace,
        claim_ids=[claim.id],
        instructions=instructions,
    )
    config = Config(
        base_url="https://provider.invalid/v1",
        model="model-1",
        data_tier="real",
        api_key="must-not-persist",
    )

    request = prepare_egress_request(
        workspace,
        prompt=prompt,
        purpose="draft_generation",
        config=config,
        source_refs=source_refs,
    )

    wire_text = request.envelope.messages[0]["content"]
    for secret in secrets:
        assert secret not in wire_text
    assert categories <= set(request.identifier_categories)
    assert request.identifier_categories == sorted(set(request.identifier_categories))
    assert request.status == "prepared"
    assert request.content_hash == canonical_hash(request)
    assert request.workspace_id == "case-a"
    assert request.source_refs == [
        SourceRef(kind="claim", id=claim.id, version=claim.version)
    ]
    assert request.provider_base_url == config.base_url
    assert request.envelope.model == config.model
    assert request.envelope.messages == [{"role": "user", "content": wire_text}]
    assert re.fullmatch(r"[A-Za-z0-9_-]+", request.request_id)

    persisted = get_egress_request(workspace, request.request_id)
    assert persisted == request
    persisted_json = (workspace / "egress" / f"{request.request_id}.json").read_text(
        encoding="utf-8"
    )
    assert "token_map" not in persisted_json
    assert "must-not-persist" not in persisted_json


def test_prepare_records_identifier_category_containing_digits(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = prepare_egress_request(
        workspace,
        prompt="The client is 95 years old.",
        purpose="draft_generation",
        config=Config(base_url="https://provider.invalid/v1", model="model-1"),
        source_refs=[],
    )

    assert request.identifier_categories == ["age_over_89"]


def test_prepare_blocks_residual_identifiers_without_writing_request(tmp_path, monkeypatch):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    config = Config(base_url="https://provider.invalid/v1", model="model-1")
    secret = "evaluator@example.com"

    monkeypatch.setattr(
        "psychtool.core.egress.redact_text",
        lambda text, *, known_names=(): (text, {}),
    )

    with pytest.raises(EgressBlockedError) as caught:
        prepare_egress_request(
            workspace,
            prompt=f"Send to {secret}",
            purpose="section_generation",
            config=config,
            source_refs=[],
        )

    assert caught.value.categories == ("email",)
    assert caught.value.__dict__ == {"categories": ("email",)}
    assert secret not in str(caught.value)
    assert list((workspace / "egress").glob("*.json")) == []


def _prepare_request(
    workspace,
    *,
    data_tier="real",
    source_refs=None,
    prompt="Safe synthetic prompt.",
):
    return prepare_egress_request(
        workspace,
        prompt=prompt,
        purpose="draft_generation",
        config=Config(
            base_url="https://provider.invalid/v1",
            model="model-1",
            data_tier=data_tier,
        ),
        source_refs=source_refs or [],
    )


def test_human_approval_requires_reviewer_and_matching_hash(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="real")

    approved = approve_human(
        workspace,
        request.request_id,
        reviewer=" reviewer-1 ",
        content_hash=request.content_hash,
    )

    assert approved.status == "approved"
    assert approved.approval_mode == "human"
    assert approved.reviewer == "reviewer-1"
    assert approved.approval_reason is None
    assert approved.approved_at is not None
    assert get_egress_request(workspace, request.request_id) == approved
    assert canonical_hash(approved) == request.content_hash


@pytest.mark.parametrize("reviewer", ["", " ", "\t\n"])
def test_human_approval_rejects_blank_reviewer(tmp_path, reviewer):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="real")

    with pytest.raises(EgressApprovalError):
        approve_human(
            workspace,
            request.request_id,
            reviewer=reviewer,
            content_hash=request.content_hash,
        )

    assert get_egress_request(workspace, request.request_id).status == "prepared"


def test_human_approval_wrong_hash_invalidates_request(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(
        workspace,
        data_tier="real",
        prompt="Do not expose secret prompt contents.",
    )

    with pytest.raises(EgressApprovalError) as caught:
        approve_human(
            workspace,
            request.request_id,
            reviewer="reviewer-1",
            content_hash="wrong-hash",
        )

    invalidated = get_egress_request(workspace, request.request_id)
    assert invalidated.status == "invalidated"
    assert invalidated.approval_mode is None
    assert invalidated.reviewer is None
    assert invalidated.approved_at is None
    assert "secret prompt contents" not in str(caught.value)
    assert "wrong-hash" not in str(caught.value)


def test_synthetic_auto_approval_requires_synthetic_tier_and_reason(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")

    approved = approve_synthetic(
        workspace,
        request.request_id,
        reason=" automated synthetic fixture ",
        content_hash=request.content_hash,
    )

    assert approved.status == "approved"
    assert approved.approval_mode == "synthetic_auto"
    assert approved.approval_reason == "automated synthetic fixture"
    assert approved.reviewer is None
    assert approved.approved_at is not None
    assert canonical_hash(approved) == request.content_hash


@pytest.mark.parametrize("reason", ["", " ", "\t\n"])
def test_synthetic_auto_approval_rejects_blank_reason(tmp_path, reason):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")

    with pytest.raises(EgressApprovalError):
        approve_synthetic(
            workspace, request.request_id, reason=reason, content_hash=request.content_hash,
        )

    assert get_egress_request(workspace, request.request_id).status == "prepared"


def test_synthetic_auto_approval_rejects_real_data(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="real")

    with pytest.raises(EgressApprovalError):
        approve_synthetic(
            workspace,
            request.request_id,
            reason="not sufficient for real data",
            content_hash=request.content_hash,
        )

    assert get_egress_request(workspace, request.request_id).status == "prepared"


def test_second_approval_is_rejected(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")
    approve_synthetic(
        workspace, request.request_id, reason="synthetic fixture",
        content_hash=request.content_hash,
    )

    with pytest.raises(EgressStateError):
        approve_synthetic(
            workspace, request.request_id, reason="try again", content_hash=request.content_hash,
        )

    persisted = get_egress_request(workspace, request.request_id)
    assert persisted.status == "approved"
    assert persisted.approval_reason == "synthetic fixture"


def test_concurrent_human_approvals_allow_at_most_one_success(tmp_path, monkeypatch):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="real")
    first_save_entered = threading.Event()
    second_at_actual_acquire = threading.Event()
    release_first_save = threading.Event()
    save_count_lock = threading.Lock()
    save_count = 0
    original_save = save_egress_request

    class ObservedMutex:
        def __init__(self):
            self._lock = threading.Lock()
            self._count_lock = threading.Lock()
            self._acquire_count = 0

        def acquire(self, *args, **kwargs):
            with self._count_lock:
                self._acquire_count += 1
                current_acquire = self._acquire_count
            if current_acquire == 2:
                second_at_actual_acquire.set()
            return self._lock.acquire(*args, **kwargs)

        def release(self):
            self._lock.release()

    transition_lock_path = egress_module._transition_lock_path(
        workspace,
        request.request_id,
    ).resolve()
    with egress_module._TRANSITION_MUTEXES_GUARD:
        monkeypatch.setitem(
            egress_module._TRANSITION_MUTEXES,
            transition_lock_path,
            ObservedMutex(),
        )

    def controlled_save(workspace_arg, request_arg):
        nonlocal save_count
        if request_arg.status == "approved":
            with save_count_lock:
                save_count += 1
                current_save = save_count
            if current_save == 1:
                first_save_entered.set()
                assert release_first_save.wait(timeout=5)
        return original_save(workspace_arg, request_arg)

    monkeypatch.setattr("psychtool.core.egress.save_egress_request", controlled_save)
    successes = []
    failures = []

    def approve(reviewer):
        try:
            successes.append(
                approve_human(
                    workspace,
                    request.request_id,
                    reviewer=reviewer,
                    content_hash=request.content_hash,
                )
            )
        except Exception as error:  # captured for deterministic thread assertions
            failures.append(error)

    first = threading.Thread(target=approve, args=("reviewer-1",))
    second = threading.Thread(target=approve, args=("reviewer-2",))
    first.start()
    assert first_save_entered.wait(timeout=2)
    second.start()
    reached_actual_acquire = second_at_actual_acquire.wait(timeout=2)
    release_first_save.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert reached_actual_acquire
    assert not first.is_alive()
    assert not second.is_alive()
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], EgressStateError)
    assert get_egress_request(workspace, request.request_id).status == "approved"


def test_synthetic_approval_clears_preexisting_reviewer(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")
    save_egress_request(
        workspace,
        request.model_copy(update={"reviewer": "forged-reviewer"}),
    )

    approved = approve_synthetic(
        workspace,
        request.request_id,
        reason="synthetic fixture",
        content_hash=request.content_hash,
    )

    assert approved.reviewer is None
    assert get_egress_request(workspace, request.request_id).reviewer is None


def test_human_approval_clears_preexisting_synthetic_reason(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="real")
    save_egress_request(
        workspace,
        request.model_copy(update={"approval_reason": "forged synthetic reason"}),
    )

    approved = approve_human(
        workspace,
        request.request_id,
        reviewer="reviewer-1",
        content_hash=request.content_hash,
    )

    assert approved.approval_reason is None
    assert get_egress_request(workspace, request.request_id).approval_reason is None


def test_existing_transition_lock_fails_closed_without_removing_lock(tmp_path):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")
    lock_path = workspace / "egress" / f".{request.request_id}.transition.lock"
    lock_path.write_text("foreign-owner", encoding="ascii")

    with pytest.raises(EgressStateError):
        approve_synthetic(
            workspace, request.request_id, reason="synthetic fixture",
            content_hash=request.content_hash,
        )

    assert lock_path.read_text(encoding="ascii") == "foreign-owner"
    assert get_egress_request(workspace, request.request_id).status == "prepared"


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


def _build_versioned_sources(workspace):
    material = import_material(
        workspace,
        material_id="material-1",
        title="Synthetic material",
        provider="synthetic provider",
        date="synthetic date",
        text="Synthetic source passage.",
    )
    claim = add_claim(workspace, claim_id="claim-1", **_claim_fields())
    frozen = freeze_draft_input(
        workspace,
        claim_ids=[claim.id],
        instructions="Use the synthetic source.",
    )
    draft = persist_generated_draft(
        workspace,
        draft_id="draft-1",
        frozen_input=frozen,
        text="Synthetic draft.",
    )
    return material, claim, draft


@pytest.mark.parametrize("stale_kind", ["claim", "material", "draft"])
def test_source_version_change_invalidates_approved_request(tmp_path, stale_kind):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    material, claim, draft = _build_versioned_sources(workspace)
    refs = {
        "claim": SourceRef(kind="claim", id=claim.id, version=claim.version),
        "material": SourceRef(kind="material", id=material.id, version=material.version),
        "draft": SourceRef(kind="draft", id=draft.id, version=draft.version),
    }
    request = _prepare_request(
        workspace,
        data_tier="real",
        source_refs=[refs[stale_kind]],
    )
    approve_human(
        workspace,
        request.request_id,
        reviewer="reviewer-1",
        content_hash=request.content_hash,
    )
    validate_source_refs(workspace, [refs[stale_kind]])
    validate_request_sources(workspace, request.request_id)

    if stale_kind == "claim":
        add_claim(
            workspace,
            claim_id=claim.id,
            **_claim_fields(text="Updated synthetic observation."),
        )
    elif stale_kind == "material":
        import_material(
            workspace,
            material_id=material.id,
            title="Updated synthetic material",
            provider="synthetic provider",
            date="updated synthetic date",
            text="Updated synthetic source passage.",
        )
    else:
        frozen = freeze_draft_input(
            workspace,
            claim_ids=[claim.id],
            instructions="Update from the synthetic source.",
        )
        persist_generated_draft(
            workspace,
            draft_id=draft.id,
            frozen_input=frozen,
            text="Updated synthetic draft.",
        )

    with pytest.raises(EgressStaleError):
        validate_source_refs(workspace, [refs[stale_kind]])
    with pytest.raises(EgressStaleError):
        validate_request_sources(workspace, request.request_id)

    assert get_egress_request(workspace, request.request_id).status == "invalidated"


def test_freshness_invalidation_cannot_be_overwritten_by_approval_snapshot(
    tmp_path, monkeypatch
):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    _, claim, _ = _build_versioned_sources(workspace)
    request = _prepare_request(
        workspace,
        data_tier="real",
        source_refs=[SourceRef(kind="claim", id=claim.id, version=claim.version)],
    )
    add_claim(
        workspace,
        claim_id=claim.id,
        **_claim_fields(text="Updated synthetic observation."),
    )

    approval_save_entered = threading.Event()
    invalidated_saved = threading.Event()
    original_save = save_egress_request
    lock_path = workspace / "egress" / f".{request.request_id}.transition.lock"

    def controlled_save(workspace_arg, request_arg):
        if request_arg.status == "approved":
            approval_save_entered.set()
            if not lock_path.exists():
                assert invalidated_saved.wait(timeout=2)
        result = original_save(workspace_arg, request_arg)
        if request_arg.status == "invalidated":
            invalidated_saved.set()
        return result

    monkeypatch.setattr("psychtool.core.egress.save_egress_request", controlled_save)
    approval_errors = []
    validation_errors = []

    def approve():
        try:
            approve_human(
                workspace,
                request.request_id,
                reviewer="reviewer-1",
                content_hash=request.content_hash,
            )
        except Exception as error:  # captured for deterministic thread assertions
            approval_errors.append(error)

    def validate():
        try:
            validate_request_sources(workspace, request.request_id)
        except Exception as error:  # captured for deterministic thread assertions
            validation_errors.append(error)

    approval_thread = threading.Thread(target=approve)
    validation_thread = threading.Thread(target=validate)
    approval_thread.start()
    assert approval_save_entered.wait(timeout=2)
    validation_thread.start()
    approval_thread.join(timeout=2)
    validation_thread.join(timeout=2)

    assert not approval_thread.is_alive()
    assert not validation_thread.is_alive()
    assert approval_errors == []
    assert len(validation_errors) == 1
    assert isinstance(validation_errors[0], EgressStaleError)
    assert invalidated_saved.is_set()
    assert get_egress_request(workspace, request.request_id).status == "invalidated"


@pytest.mark.parametrize("kind", ["claim", "material", "draft"])
def test_missing_source_is_stale_without_leaking_source_id(tmp_path, kind):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    missing_id = "sensitive-source-id"

    with pytest.raises(EgressStaleError) as caught:
        validate_source_refs(
            workspace,
            [SourceRef(kind=kind, id=missing_id, version=1)],
        )

    assert missing_id not in str(caught.value)
    assert caught.value.__dict__ == {}


def test_send_holds_transition_lock_through_sent_persistence(tmp_path, monkeypatch):
    workspace = init_workspace(tmp_path / "workspace", case_id="case-a")
    request = _prepare_request(workspace, data_tier="synthetic")
    approved = approve_synthetic(
        workspace,
        request.request_id,
        reason="synthetic fixture",
        content_hash=request.content_hash,
    )
    transport_entered = threading.Event()
    invalidation_at_actual_acquire = threading.Event()
    release_transport = threading.Event()

    class ObservedMutex:
        def __init__(self):
            self._lock = threading.Lock()
            self._count_lock = threading.Lock()
            self._acquire_count = 0

        def acquire(self, *args, **kwargs):
            with self._count_lock:
                self._acquire_count += 1
                current_acquire = self._acquire_count
            if current_acquire == 2:
                invalidation_at_actual_acquire.set()
            return self._lock.acquire(*args, **kwargs)

        def release(self):
            self._lock.release()

    transition_lock_path = egress_module._transition_lock_path(
        workspace,
        request.request_id,
    ).resolve()
    with egress_module._TRANSITION_MUTEXES_GUARD:
        monkeypatch.setitem(
            egress_module._TRANSITION_MUTEXES,
            transition_lock_path,
            ObservedMutex(),
        )

    def blocking_transport(config, envelope):
        transport_entered.set()
        assert release_transport.wait(timeout=5)
        return "Clean generated text."

    send_errors = []
    invalidation_errors = []

    def send():
        try:
            send_approved(
                workspace,
                approved.request_id,
                config=Config(
                    base_url="https://provider.invalid/v1",
                    model="model-1",
                    data_tier="synthetic",
                ),
                transport=blocking_transport,
            )
        except Exception as error:  # captured for deterministic thread assertions
            send_errors.append(error)

    def invalidate():
        try:
            invalidate_request(workspace, approved.request_id)
        except Exception as error:  # captured for deterministic thread assertions
            invalidation_errors.append(error)

    send_thread = threading.Thread(target=send)
    invalidation_thread = threading.Thread(target=invalidate)
    send_thread.start()
    assert transport_entered.wait(timeout=2)
    invalidation_thread.start()
    assert invalidation_at_actual_acquire.wait(timeout=2)
    release_transport.set()
    send_thread.join(timeout=2)
    invalidation_thread.join(timeout=2)

    assert not send_thread.is_alive()
    assert not invalidation_thread.is_alive()
    assert send_errors == []
    assert len(invalidation_errors) == 1
    assert isinstance(invalidation_errors[0], EgressStateError)
    assert get_egress_request(workspace, approved.request_id).status == "sent"
