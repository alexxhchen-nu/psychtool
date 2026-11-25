"""Model-egress request records, canonical hashing, and persistence.

The safety state machine (prepare -> approve -> send, approval-hash check,
stale-source invalidation) is implemented exactly once here and in
``psychtool.gateway.client``. Persistence goes through the small
:class:`~psychtool.core.egress_store.EgressStore` protocol so the JSON
workspace directory (ADR 0005) and the SQLite case store (ADR 0010) share
one implementation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Union
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator

from psychtool.config import Config, DataTier
from psychtool.core.egress_store import (
    EgressStore,
    JsonDirStore,
    egress_transition_lock,
)
from psychtool.core.redact import IDENTIFIER_KINDS, find_identifiers, redact_text
from psychtool.core.workspace import get_known_names

# Anything the egress pipeline can persist through: a legacy JSON workspace
# directory, or any object satisfying the egress store protocol.
EgressTarget = Union[Path, str, EgressStore]


def _as_egress_store(target: EgressTarget) -> EgressStore:
    """Resolve a persistence target; JSON directories get the file adapter."""
    if isinstance(target, (str, Path)):
        return JsonDirStore(Path(target))
    return target

EgressPurpose = Literal["section_generation", "draft_generation", "judge", "eval"]
EgressStatus = Literal["prepared", "approved", "sent", "invalidated"]
ApprovalMode = Literal["human", "synthetic_auto"]
EgressEvent = Literal[
    "prepared",
    "approved",
    "invalidated",
    "sent",
    "transport_error",
]
EgressErrorCategory = Literal["transport_error"]


class EgressRunner(ABC):
    """Nominal model runner whose every call carries provenance and purpose."""

    @abstractmethod
    def run(
        self,
        *,
        workspace: Path,
        prompt: str,
        purpose: EgressPurpose,
        source_refs: list["SourceRef"],
    ) -> str:
        """Run one request through a policy-enforcing egress implementation."""


def require_egress_runner(runner: object) -> EgressRunner:
    """Reject structural lookalikes before they can receive a model prompt."""
    if not isinstance(runner, EgressRunner):
        raise TypeError("runner must be an EgressRunner")
    return runner


EGRESS_DIR = "egress"
_HASH_EXCLUDED_FIELDS = {
    "content_hash",
    "status",
    "approval_mode",
    "reviewer",
    "approval_reason",
    "prepared_at",
    "approved_at",
    "sent_at",
}
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_CONTENT_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_CATEGORY_KEYS = frozenset(IDENTIFIER_KINDS)
_TOKEN_CATEGORY = re.compile(r"^\[\[([A-Z0-9_]+)_\d+\]\]$")
_TRANSITION_MUTEXES: dict[Path, threading.Lock] = {}
_TRANSITION_MUTEXES_GUARD = threading.Lock()


class EgressBlockedError(RuntimeError):
    """Raised when a prepared prompt still contains identifier categories."""

    def __init__(self, categories: list[str]) -> None:
        self.categories = tuple(sorted(set(categories)))
        super().__init__(
            "egress blocked; residual identifier categories: "
            + ", ".join(self.categories)
        )


class EgressApprovalError(RuntimeError):
    """Raised when an approval does not meet the egress policy."""


class EgressStateError(RuntimeError):
    """Raised when an egress state transition is not allowed."""


class EgressStaleError(RuntimeError):
    """Raised when an egress request refers to a missing or old source."""


def _validate_request_id(request_id: str) -> str:
    if not _SAFE_REQUEST_ID.fullmatch(request_id):
        raise ValueError("request_id must contain only ASCII letters, digits, '_' or '-'")
    return request_id


class SourceRef(BaseModel):
    kind: Literal["claim", "material", "draft"]
    id: str
    version: int


class OutboundEnvelope(BaseModel):
    model: str
    messages: list[dict[str, str]]


class EgressRequest(BaseModel):
    request_id: str
    workspace_id: str
    purpose: EgressPurpose
    data_tier: DataTier
    provider_base_url: str
    envelope: OutboundEnvelope
    source_refs: list[SourceRef]
    identifier_categories: list[str]
    content_hash: str
    status: EgressStatus
    approval_mode: ApprovalMode | None = None
    reviewer: str | None = None
    approval_reason: str | None = None
    prepared_at: str
    approved_at: str | None = None
    sent_at: str | None = None

    @field_validator("request_id")
    @classmethod
    def _request_id_safe(cls, value: str) -> str:
        return _validate_request_id(value)


def canonical_hash(request: EgressRequest | dict) -> str:
    """Return the SHA-256 hash of the request's approval-relevant content."""
    validated = request if isinstance(request, EgressRequest) else EgressRequest.model_validate(request)
    canonical = validated.model_dump(mode="json", exclude=_HASH_EXCLUDED_FIELDS)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_event_timestamp(value: object, *, optional: bool) -> bool:
    if value is None:
        return optional
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def serialize_egress_event(
    request: EgressRequest,
    *,
    event: EgressEvent,
    timestamp: str | None = None,
    error_category: EgressErrorCategory | None = None,
) -> dict[str, object]:
    """Return defensively validated, allowlisted egress security metadata."""
    try:
        validated = EgressRequest.model_validate(
            request.model_dump(mode="python", warnings=False)
        )
    except (AttributeError, TypeError, ValueError):
        raise ValueError("invalid egress event metadata") from None

    if not isinstance(event, str) or event not in {
        "prepared",
        "approved",
        "invalidated",
        "sent",
        "transport_error",
    }:
        raise ValueError("invalid egress event metadata")
    if error_category is not None and not isinstance(error_category, str):
        raise ValueError("invalid egress event metadata")
    if error_category not in {None, "transport_error"}:
        raise ValueError("invalid egress event metadata")
    if (event == "transport_error") != (error_category == "transport_error"):
        raise ValueError("invalid egress event metadata")
    if not isinstance(validated.content_hash, str) or not _SAFE_CONTENT_HASH.fullmatch(
        validated.content_hash
    ):
        raise ValueError("invalid egress event metadata")
    if any(
        category not in _IDENTIFIER_CATEGORY_KEYS
        for category in validated.identifier_categories
    ):
        raise ValueError("invalid egress event metadata")
    if not _valid_event_timestamp(validated.prepared_at, optional=False):
        raise ValueError("invalid egress event metadata")
    if not _valid_event_timestamp(validated.approved_at, optional=True):
        raise ValueError("invalid egress event metadata")
    if not _valid_event_timestamp(validated.sent_at, optional=True):
        raise ValueError("invalid egress event metadata")
    if not _valid_event_timestamp(timestamp, optional=True):
        raise ValueError("invalid egress event metadata")

    serialized: dict[str, object] = {
        "event": event,
        "request_id": validated.request_id,
        "content_hash": validated.content_hash,
        "purpose": validated.purpose,
        "data_tier": validated.data_tier,
        "provider": urlparse(validated.provider_base_url).hostname or "unknown",
        "model": validated.envelope.model,
        "identifier_categories": list(validated.identifier_categories),
        "status": validated.status,
        "reviewer_fingerprint": (
            hashlib.sha256(validated.reviewer.encode("utf-8")).hexdigest()
            if validated.reviewer is not None else None
        ),
        "prepared_at": validated.prepared_at,
        "approved_at": validated.approved_at,
        "sent_at": validated.sent_at,
    }
    if timestamp is not None:
        serialized["timestamp"] = timestamp
    if error_category is not None:
        serialized["error_category"] = error_category
    return serialized


def prepare_egress_request(
    workspace: EgressTarget,
    *,
    prompt: str,
    purpose: EgressPurpose,
    config: Config,
    source_refs: list[SourceRef],
) -> EgressRequest:
    """Redact and persist the complete request that will later be reviewed."""
    store = _as_egress_store(workspace)
    if isinstance(store, JsonDirStore):
        known_names = get_known_names(store.workspace)
    else:
        known_names = store.get_known_names()
    redacted_prompt, token_map = redact_text(prompt, known_names=known_names)

    identifier_categories: set[str] = set()
    for token in token_map:
        match = _TOKEN_CATEGORY.fullmatch(token)
        if match is not None:
            identifier_categories.add(match.group(1).lower())

    residual_findings = find_identifiers(redacted_prompt)
    if residual_findings:
        raise EgressBlockedError(
            [finding["category"] for finding in residual_findings]
        )

    workspace_id = store.case_id
    request = EgressRequest(
        request_id=secrets.token_urlsafe(18),
        workspace_id=workspace_id,
        purpose=purpose,
        data_tier=config.data_tier,
        provider_base_url=config.base_url,
        envelope=OutboundEnvelope(
            model=config.model,
            messages=[{"role": "user", "content": redacted_prompt}],
        ),
        source_refs=source_refs,
        identifier_categories=sorted(identifier_categories),
        content_hash="",
        status="prepared",
        prepared_at=datetime.now(timezone.utc).isoformat(),
    )
    request = request.model_copy(update={"content_hash": canonical_hash(request)})
    store.save_egress_request(request)
    return request


def _egress_dir(workspace: Path) -> Path:
    directory = Path(workspace) / EGRESS_DIR
    directory.mkdir(exist_ok=True)
    return directory


def save_egress_request(workspace: EgressTarget, request: EgressRequest) -> Path | None:
    """Persist a request; JSON workspaces write atomically, SQLite updates a row."""
    store = _as_egress_store(workspace)
    if not isinstance(store, JsonDirStore):
        store.save_egress_request(request)
        return None
    request_id = _validate_request_id(request.request_id)
    directory = _egress_dir(store.workspace)
    destination = directory / f"{request_id}.json"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{request_id}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(request.model_dump_json(indent=2))
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


def get_egress_request(workspace: EgressTarget, request_id: str) -> EgressRequest:
    """Load a persisted request, lazily upgrading an older workspace layout."""
    request_id = _validate_request_id(request_id)
    store = _as_egress_store(workspace)
    if not isinstance(store, JsonDirStore):
        return store.get_egress_request(request_id)
    path = _egress_dir(store.workspace) / f"{request_id}.json"
    return EgressRequest.model_validate_json(path.read_text(encoding="utf-8"))


def _transition_lock_path(workspace: Path, request_id: str) -> Path:
    request_id = _validate_request_id(request_id)
    return _egress_dir(workspace) / f".{request_id}.transition.lock"


@contextmanager
def _request_transition_lock(workspace: EgressTarget, request_id: str) -> Iterator[None]:
    """Serialize one request's transitions and leave crash-created locks closed."""
    store = _as_egress_store(workspace)
    if isinstance(store, JsonDirStore):
        # Legacy JSON path keeps its own lock-file implementation so existing
        # on-disk workspaces and their tests behave exactly as before.
        with _json_request_transition_lock(store.workspace, request_id):
            yield
        return
    with egress_transition_lock(store, request_id):
        yield


@contextmanager
def _json_request_transition_lock(workspace: Path, request_id: str) -> Iterator[None]:
    lock_path = _transition_lock_path(workspace, request_id)
    with _TRANSITION_MUTEXES_GUARD:
        mutex = _TRANSITION_MUTEXES.setdefault(lock_path.resolve(), threading.Lock())

    owner = secrets.token_hex(32)
    created = False
    mutex.acquire()
    try:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            raise EgressStateError("egress request transition is locked") from None
        created = True
        with os.fdopen(descriptor, mode="w", encoding="ascii") as lock_file:
            lock_file.write(owner)
            lock_file.flush()
            os.fsync(lock_file.fileno())
        yield
    finally:
        try:
            if created:
                try:
                    current_owner = lock_path.read_text(encoding="ascii")
                except (FileNotFoundError, OSError, UnicodeError):
                    current_owner = None
                if current_owner == owner:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        raise EgressStateError(
                            "egress request transition cleanup failed"
                        ) from None
        finally:
            mutex.release()


def _invalidate_request_locked(workspace: EgressTarget, request_id: str) -> EgressRequest:
    store = _as_egress_store(workspace)
    request = get_egress_request(store, request_id)
    if request.status == "invalidated":
        return request
    if request.status == "sent":
        raise EgressStateError("sent egress requests cannot be invalidated")
    invalidated = request.model_copy(update={"status": "invalidated"})
    store.save_egress_request(invalidated)
    return invalidated


def invalidate_request(workspace: EgressTarget, request_id: str) -> EgressRequest:
    """Reload and atomically mark an unsent request as invalidated."""
    with _request_transition_lock(workspace, request_id):
        return _invalidate_request_locked(workspace, request_id)


def _prepared_request(workspace: EgressTarget, request_id: str) -> EgressRequest:
    request = get_egress_request(workspace, request_id)
    if request.status != "prepared":
        raise EgressStateError("egress request is not prepared")
    return request


def approve_human(
    workspace: EgressTarget,
    request_id: str,
    *,
    reviewer: str,
    content_hash: str,
) -> EgressRequest:
    """Approve the exact prepared content after an identified human review."""
    with _request_transition_lock(workspace, request_id):
        request = _prepared_request(workspace, request_id)
        reviewer = reviewer.strip()
        if not reviewer:
            raise EgressApprovalError("human approval requires a reviewer")
        if (
            not secrets.compare_digest(content_hash, request.content_hash)
            or canonical_hash(request) != request.content_hash
        ):
            _invalidate_request_locked(workspace, request_id)
            raise EgressApprovalError("egress content hash does not match")

        approved = request.model_copy(
            update={
                "status": "approved",
                "approval_mode": "human",
                "reviewer": reviewer,
                "approval_reason": None,
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _as_egress_store(workspace).save_egress_request(approved)
        return approved


def approve_synthetic(
    workspace: EgressTarget,
    request_id: str,
    *,
    reason: str,
    content_hash: str,
) -> EgressRequest:
    """Automatically approve the caller's exact prepared synthetic request."""
    with _request_transition_lock(workspace, request_id):
        request = _prepared_request(workspace, request_id)
        reason = reason.strip()
        if request.data_tier != "synthetic":
            raise EgressApprovalError("synthetic auto-approval requires synthetic data")
        if not reason:
            raise EgressApprovalError("synthetic auto-approval requires a reason")
        if (
            not secrets.compare_digest(content_hash, request.content_hash)
            or canonical_hash(request) != request.content_hash
        ):
            _invalidate_request_locked(workspace, request_id)
            raise EgressApprovalError("egress content hash does not match")

        approved = request.model_copy(
            update={
                "status": "approved",
                "approval_mode": "synthetic_auto",
                "reviewer": None,
                "approval_reason": reason,
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _as_egress_store(workspace).save_egress_request(approved)
        return approved
