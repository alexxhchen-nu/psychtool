"""The single strict model-egress gateway.

Only a persisted, approved :class:`EgressRequest` may reach a transport. The
approved envelope is passed through unchanged, and the injected transport keeps
unit tests off the network.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from psychtool.config import Config
from psychtool.core.egress import (
    EgressRequest,
    EgressStaleError,
    EgressStateError,
    _egress_dir,
    _invalidate_request_locked,
    _request_transition_lock,
    _validate_request_id,
    canonical_hash,
    get_egress_request,
    save_egress_request,
)
from psychtool.core.redact import gate_pii
from psychtool.core.review import validate_source_refs
from psychtool.core.workspace import get_known_names


class NetworkForbiddenError(RuntimeError):
    """Raised when a model call would violate the current data tier."""


class EgressOutputBlockedError(RuntimeError):
    """Raised when a provider response contains identifier categories."""

    def __init__(self, categories: list[str]) -> None:
        self.categories = tuple(sorted(set(categories)))
        super().__init__(
            "egress output blocked; identifier categories: "
            + ", ".join(self.categories)
        )


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_local(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.hostname in _LOCAL_HOSTS


def _send_lock_path(workspace: Path, request_id: str) -> Path:
    request_id = _validate_request_id(request_id)
    return _egress_dir(Path(workspace)) / f"{request_id}.send.lock"


def _remove_owned_send_lock(lock_path: Path, owner: str) -> None:
    try:
        current_owner = lock_path.read_text(encoding="ascii")
    except (FileNotFoundError, OSError, UnicodeError):
        return
    if current_owner == owner:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _acquire_send_lock(workspace: Path, request_id: str) -> tuple[Path, str]:
    lock_path = _send_lock_path(workspace, request_id)
    owner = secrets.token_hex(32)
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        raise EgressStateError("egress request send is locked") from None

    try:
        with os.fdopen(descriptor, mode="w", encoding="ascii") as lock_file:
            lock_file.write(owner)
            lock_file.flush()
            os.fsync(lock_file.fileno())
    except BaseException:
        _remove_owned_send_lock(lock_path, owner)
        raise
    return lock_path, owner


def _validate_approved_state(request: EgressRequest) -> None:
    if request.status != "approved":
        raise EgressStateError("egress request is not approved")
    if request.approval_mode == "human":
        if request.reviewer is None or not request.reviewer.strip():
            raise EgressStateError("egress request approval is invalid")
    elif request.approval_mode == "synthetic_auto":
        if (
            request.data_tier != "synthetic"
            or request.approval_reason is None
            or not request.approval_reason.strip()
        ):
            raise EgressStateError("egress request approval is invalid")
    else:
        raise EgressStateError("egress request approval is invalid")


def _validate_routing(request: EgressRequest, config: Config) -> None:
    if (
        config.model != request.envelope.model
        or config.base_url != request.provider_base_url
        or config.data_tier != request.data_tier
    ):
        raise EgressStateError("egress request configuration does not match approval")
    if not secrets.compare_digest(canonical_hash(request), request.content_hash):
        raise EgressStateError("egress request content hash does not match approval")
    if request.data_tier == "real" and not _is_local(request.provider_base_url):
        raise NetworkForbiddenError(
            "network egress forbidden under data_tier='real'; refusing non-local endpoint"
        )


def send_approved(
    workspace: Path,
    request_id: str,
    *,
    config: Config,
    transport: Callable[[Config, dict], str],
) -> str:
    """Send one persisted approved envelope exactly once.

    Lock order is always send lock followed by request transition lock. The
    transition lock remains held through transport completion and atomic
    persistence of the ``sent`` state.
    """
    lock_path, owner = _acquire_send_lock(Path(workspace), request_id)
    phase = "validation"
    try:
        with _request_transition_lock(workspace, request_id):
            request = get_egress_request(workspace, request_id)
            _validate_approved_state(request)
            try:
                validate_source_refs(workspace, request.source_refs)
            except EgressStaleError:
                _invalidate_request_locked(workspace, request_id)
                raise
            _validate_routing(request, config)

            phase = "transport"
            response = transport(config, request.envelope.model_dump())
            phase = "after_transport"

            sent = request.model_copy(
                update={
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            save_egress_request(workspace, sent)
            phase = "sent"
    except Exception:
        if phase == "validation":
            _remove_owned_send_lock(lock_path, owner)
        # A transport error can follow delivery; keep the lock to prevent replay.
        if phase == "transport":
            raise RuntimeError("model transport failed") from None
        raise

    findings = gate_pii(response, known_names=get_known_names(workspace))
    categories = sorted({finding["category"] for finding in findings})
    _remove_owned_send_lock(lock_path, owner)
    if categories:
        raise EgressOutputBlockedError(categories)
    return response
