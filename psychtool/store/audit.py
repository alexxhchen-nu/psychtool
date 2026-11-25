"""Append-only audit log with a SHA-256 hash chain (ADR 0011).

The audit trail lives inside the case database (``audit_log`` table, schema
v2) instead of a JSONL sidecar so that one transaction can commit a state
change and the audit row that describes it — a crash can never leave one
without the other. Append-only is enforced two ways:

- ``BEFORE UPDATE`` / ``BEFORE DELETE`` triggers abort with
  ``audit log is append-only`` on the normal application path;
- ``entry_hash = sha256(canonical JSON of every other column incl.
  prev_hash)`` chains rows genesis-forward, so tampering that bypasses the
  triggers (someone with file access dropping them) is *detectable* via
  :func:`verify_audit_chain` — the chain makes edits evident, not impossible.

Nothing user-authored may enter the log. The writer accepts only allowlisted
``action`` / ``object_type`` / ``destination`` values, identifier-shaped
``object_id`` values, and 64-hex ``content_hash`` digests; free text is
rejected structurally, before SQL runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.store.sqlite_store import SqliteStore

# Fixed vocabularies: adding an event means extending these sets (and the
# ADR), never passing caller text through.
AuditAction = Literal[
    "case.create",
    "case.import_json",
    "material.import",
    "claim.accept",
    "section.save",
    "egress.prepare",
    "egress.approve",
    "egress.invalidate",
    "egress.send",
    "egress.output_blocked",
    "egress.send_lock_recovered",
    "egress.transition_lock_recovered",
]
AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "case.create",
        "case.import_json",
        "material.import",
        "claim.accept",
        "section.save",
        "egress.prepare",
        "egress.approve",
        "egress.invalidate",
        "egress.send",
        "egress.output_blocked",
        "egress.send_lock_recovered",
        "egress.transition_lock_recovered",
    }
)
AUDIT_OBJECT_TYPES: frozenset[str] = frozenset(
    {"case", "material", "claim", "section", "egress_request"}
)
AUDIT_DESTINATIONS: frozenset[str] = frozenset({"fake", "http"})

# Same shape as the store's generic id rule, plus the leading ``-``/``_``
# that token_urlsafe-derived ids (egress request ids) can start with. Still
# ids only — never names or free text.
_OBJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.:-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

GENESIS_PREV_HASH = "0" * 64

_CHAIN_FIELDS = (
    "case_id",
    "ts",
    "action",
    "object_type",
    "object_id",
    "content_hash",
    "destination",
    "prev_hash",
)


class AuditWriter(Protocol):
    """Anything that can append one audit row inside its own transaction."""

    def append_audit(
        self,
        *,
        case_id: str | None,
        action: str,
        object_type: str,
        object_id: str,
        content_hash: str | None = None,
        destination: str | None = None,
    ) -> None: ...


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_entry_hash(row: dict) -> str:
    """SHA-256 over the canonical JSON of all chain fields incl. prev_hash."""
    canonical = {field: row.get(field) for field in _CHAIN_FIELDS}
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate(
    *,
    action: str,
    object_type: str,
    object_id: str,
    content_hash: str | None,
    destination: str | None,
) -> None:
    if action not in AUDIT_ACTIONS:
        raise ValueError("audit action is not on the allowlist")
    if object_type not in AUDIT_OBJECT_TYPES:
        raise ValueError("audit object type is not on the allowlist")
    if not isinstance(object_id, str) or not _OBJECT_ID_RE.fullmatch(object_id):
        raise ValueError("audit object id must be a plain identifier")
    if content_hash is not None and (
        not isinstance(content_hash, str) or not _HASH_RE.fullmatch(content_hash)
    ):
        raise ValueError("audit content hash must be 64 lowercase hex chars")
    if destination is not None and destination not in AUDIT_DESTINATIONS:
        raise ValueError("audit destination is not on the allowlist")


def _insert(
    connection: sqlite3.Connection,
    *,
    case_id: str | None,
    action: str,
    object_type: str,
    object_id: str,
    content_hash: str | None,
    destination: str | None,
) -> None:
    """Append one chained row on an open connection (joins any transaction)."""
    _validate(
        action=action,
        object_type=object_type,
        object_id=object_id,
        content_hash=content_hash,
        destination=destination,
    )
    row = connection.execute(
        "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    prev_hash = row[0] if row is not None else GENESIS_PREV_HASH
    fields = {
        "case_id": case_id,
        "ts": _utcnow(),
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "content_hash": content_hash,
        "destination": destination,
        "prev_hash": prev_hash,
    }
    connection.execute(
        "INSERT INTO audit_log"
        " (case_id, ts, action, object_type, object_id, content_hash,"
        "  destination, prev_hash, entry_hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            case_id,
            fields["ts"],
            action,
            object_type,
            object_id,
            content_hash,
            destination,
            prev_hash,
            compute_entry_hash(fields),
        ),
    )


def append_audit(
    target: "AuditWriter | SqliteStore | sqlite3.Connection",
    *,
    case_id: str | None,
    action: str,
    object_type: str,
    object_id: str,
    content_hash: str | None = None,
    destination: str | None = None,
) -> None:
    """Append one audit row; free text cannot pass the structural checks.

    ``target`` may be:

    - an open :class:`sqlite3.Connection` — the row joins whatever transaction
      is already open on it, so the state change and its audit entry commit
      or roll back together;
    - a ``SqliteStore`` (anything exposing ``transaction()``) — the row is
      written in a fresh transaction on the store's connection;
    - an :class:`AuditWriter` (e.g. ``CaseStore``) — delegates.
    """
    if isinstance(target, sqlite3.Connection):
        if target.in_transaction:
            _insert(
                target,
                case_id=case_id,
                action=action,
                object_type=object_type,
                object_id=object_id,
                content_hash=content_hash,
                destination=destination,
            )
            return
        target.execute("BEGIN IMMEDIATE")
        try:
            _insert(
                target,
                case_id=case_id,
                action=action,
                object_type=object_type,
                object_id=object_id,
                content_hash=content_hash,
                destination=destination,
            )
        except BaseException:
            target.execute("ROLLBACK")
            raise
        else:
            target.execute("COMMIT")
        return
    transaction = getattr(target, "transaction", None)
    if callable(transaction):
        with transaction() as connection:
            _insert(
                connection,
                case_id=case_id,
                action=action,
                object_type=object_type,
                object_id=object_id,
                content_hash=content_hash,
                destination=destination,
            )
        return
    target.append_audit(
        case_id=case_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        content_hash=content_hash,
        destination=destination,
    )


def verify_audit_chain(store: "SqliteStore") -> tuple[bool, int, int | None]:
    """Walk the chain in seq order.

    Returns ``(ok, count, first_bad_seq)``: ``ok`` is True when every row's
    ``prev_hash`` links to the previous row's ``entry_hash`` and every
    ``entry_hash`` recomputes; ``count`` is the number of rows checked;
    ``first_bad_seq`` is the first broken row when not ok.
    """
    rows = store._connect().execute(
        "SELECT seq, case_id, ts, action, object_type, object_id, content_hash,"
        " destination, prev_hash, entry_hash FROM audit_log ORDER BY seq"
    ).fetchall()
    prev = GENESIS_PREV_HASH
    for row in rows:
        fields = {field: row[field] for field in _CHAIN_FIELDS}
        if (
            row["prev_hash"] != prev
            or compute_entry_hash(fields) != row["entry_hash"]
        ):
            return False, len(rows), row["seq"]
        prev = row["entry_hash"]
    return True, len(rows), None
