"""Fail-closed recovery of egress send locks after a crash (ADR 0011).

A server process killed between taking the SQLite send lock and releasing it
leaves a lock row behind. On the next start, ``recover_stale_send_locks``
sees the foreign boot id and:

- marks the request ``send_interrupted`` (terminal — never sendable again)
  unless the status is already ``sent`` (send finished, only unlock lost);
- appends exactly one ``egress.send_lock_recovered`` audit row per request;
- leaves locks owned by the current boot alone;
- is idempotent.

The crash cases are produced by a real child process that takes the lock via
the production code path and is then SIGKILLed.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys

import pytest

from psychtool.core.egress import approve_synthetic, prepare_egress_request
from psychtool.core.egress_store import egress_send_lock, egress_send_unlock
from psychtool.config import Config
from psychtool.store.recovery import BOOT_ID, recover_stale_send_locks
from psychtool.store.sqlite_store import SqliteStore

_CHILD_SCRIPT = """
import sys, time
from psychtool.core.egress import approve_synthetic, prepare_egress_request
from psychtool.core.egress_store import egress_send_lock
from psychtool.config import Config
from psychtool.store.sqlite_store import SqliteStore

mode = sys.argv[1]
db = sys.argv[2]
ready = sys.argv[3]

store = SqliteStore(db)
case = store.case("case-a")
config = Config(
    base_url="https://provider.invalid/v1",
    model="model-1",
    data_tier="synthetic",
    api_key="test-key",
)
request = prepare_egress_request(
    case,
    prompt="Safe synthetic prompt.",
    purpose="draft_generation",
    config=config,
    source_refs=[],
)
approved = approve_synthetic(
    case,
    request.request_id,
    reason="synthetic fixture",
    content_hash=request.content_hash,
)
egress_send_lock(case, request.request_id)
if mode == "sent":
    # Simulate a crash after the transport persisted `sent` but before the
    # lock release: flip the status, keep the lock, then die.
    sent = approved.model_copy(update={"status": "sent"})
    case.save_egress_request(sent)
with open(ready, "w") as fh:
    fh.write("locked")
time.sleep(600)  # the parent SIGKILLs us here
"""


def _make_case(tmp_path):
    store = SqliteStore(tmp_path / "psychtool.db")
    store.create_case("case-a")
    return store


def _run_child_until_locked(tmp_path, mode: str) -> str:
    """Start the crashing child and wait until it holds the send lock."""
    db = str(tmp_path / "psychtool.db")
    ready = tmp_path / "ready"
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT, mode, db, str(ready)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(600):  # up to 60 s
            if ready.exists():
                break
            if child.poll() is not None:
                stderr = child.stderr.read().decode()
                raise AssertionError(f"child exited early: {stderr}")
            import time

            time.sleep(0.1)
        else:
            raise AssertionError("child never took the send lock")
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=10)
    assert child.returncode == -signal.SIGKILL
    return db


def _audit_rows(db, action: str) -> list[dict]:
    raw = sqlite3.connect(db)
    raw.row_factory = sqlite3.Row
    rows = raw.execute(
        "SELECT * FROM audit_log WHERE action = ?", (action,)
    ).fetchall()
    raw.close()
    return [dict(r) for r in rows]


# -- (a) crash mid-send ---------------------------------------------------------


def test_sigkill_mid_send_recovers_send_interrupted(tmp_path):
    store = _make_case(tmp_path)
    db = _run_child_until_locked(tmp_path, mode="locked")

    # Restart: a fresh store over the same file sees the foreign boot id.
    restarted = SqliteStore(db)
    recovered = recover_stale_send_locks(restarted, BOOT_ID)
    assert len(recovered) == 1
    assert recovered[0]["prior_status"] == "approved"

    case = restarted.case("case-a")
    request_id = recovered[0]["request_id"]
    request = case.get_egress_request(request_id)
    assert request.status == "send_interrupted"
    # Lock cleared.
    row = restarted._connect().execute(
        "SELECT send_lock_owner, transition_lock_owner FROM egress_requests"
        " WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    assert row["send_lock_owner"] is None
    assert row["transition_lock_owner"] is None

    # Exactly one recovery audit row.
    rows = _audit_rows(db, "egress.send_lock_recovered")
    assert len(rows) == 1
    assert rows[0]["object_id"] == request_id
    assert rows[0]["content_hash"] == request.content_hash

    # A second send is refused before any transport call.
    transport_calls = []

    def transport(config, envelope):
        transport_calls.append(envelope)
        return "text"

    from psychtool.core.egress import EgressStateError
    from psychtool.gateway.client import send_approved

    config = Config(
        base_url="https://provider.invalid/v1",
        model="model-1",
        data_tier="synthetic",
        api_key="test-key",
    )
    with pytest.raises(EgressStateError):
        send_approved(case, request_id, config=config, transport=transport)
    # The transport was never called: at most one delivery in total (the
    # possibly-delivered one from the crashed child).
    assert transport_calls == []


# -- (b) crash after `sent` was persisted ---------------------------------------


def test_crash_after_sent_keeps_status_and_clears_lock(tmp_path):
    store = _make_case(tmp_path)
    db = _run_child_until_locked(tmp_path, mode="sent")

    restarted = SqliteStore(db)
    recovered = recover_stale_send_locks(restarted, BOOT_ID)
    assert len(recovered) == 1
    assert recovered[0]["prior_status"] == "sent"

    case = restarted.case("case-a")
    request = case.get_egress_request(recovered[0]["request_id"])
    assert request.status == "sent"  # delivery is not undone
    row = restarted._connect().execute(
        "SELECT send_lock_owner FROM egress_requests WHERE request_id = ?",
        (recovered[0]["request_id"],),
    ).fetchone()
    assert row["send_lock_owner"] is None
    assert len(_audit_rows(db, "egress.send_lock_recovered")) == 1


# -- (c) current-boot locks are untouched ----------------------------------------


def test_current_boot_lock_is_left_alone(tmp_path):
    store = _make_case(tmp_path)
    case = store.case("case-a")
    config = Config(
        base_url="https://provider.invalid/v1",
        model="model-1",
        data_tier="synthetic",
        api_key="test-key",
    )
    request = prepare_egress_request(
        case,
        prompt="Safe synthetic prompt.",
        purpose="draft_generation",
        config=config,
        source_refs=[],
    )
    approve_synthetic(
        case, request.request_id, reason="r", content_hash=request.content_hash
    )
    _key, owner = egress_send_lock(case, request.request_id)
    try:
        recovered = recover_stale_send_locks(store, BOOT_ID)
        assert recovered == []
        # Lock still held; audit has no recovery row.
        row = store._connect().execute(
            "SELECT send_lock_owner FROM egress_requests WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
        assert row["send_lock_owner"] == owner
        assert _audit_rows(str(tmp_path / "psychtool.db"), "egress.send_lock_recovered") == []
    finally:
        egress_send_unlock(case, request.request_id, owner)


def test_current_boot_transition_lock_is_left_alone(tmp_path):
    store = _make_case(tmp_path)
    case = store.case("case-a")
    config = Config(
        base_url="https://provider.invalid/v1",
        model="model-1",
        data_tier="synthetic",
        api_key="test-key",
    )
    request = prepare_egress_request(
        case,
        prompt="Safe synthetic prompt.",
        purpose="draft_generation",
        config=config,
        source_refs=[],
    )
    # Take the transition lock directly with a current-boot owner.
    owner = f"{BOOT_ID}:1:deadbeef"
    assert case.try_acquire_transition_lock(request.request_id, owner)
    try:
        recovered = recover_stale_send_locks(store, BOOT_ID)
        assert recovered == []
        row = store._connect().execute(
            "SELECT transition_lock_owner FROM egress_requests WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
        assert row["transition_lock_owner"] == owner
    finally:
        case.release_transition_lock(request.request_id, owner)


def test_stale_transition_lock_only_is_cleared_and_audited(tmp_path):
    """Only a stale transition lock: cleared, current-boot send lock kept,
    one ``egress.transition_lock_recovered`` audit row."""
    store = _make_case(tmp_path)
    case = store.case("case-a")
    config = Config(
        base_url="https://provider.invalid/v1",
        model="model-1",
        data_tier="synthetic",
        api_key="test-key",
    )
    request = prepare_egress_request(
        case,
        prompt="Safe synthetic prompt.",
        purpose="draft_generation",
        config=config,
        source_refs=[],
    )
    # Send lock from THIS boot, transition lock from a foreign boot.
    _key, send_owner = egress_send_lock(case, request.request_id)
    foreign_transition = "FOREIGNBOOT:99:cafe"
    store._connect().execute(
        "UPDATE egress_requests SET transition_lock_owner = ?"
        " WHERE request_id = ?",
        (foreign_transition, request.request_id),
    )
    try:
        recovered = recover_stale_send_locks(store, BOOT_ID)
        assert len(recovered) == 1
        row = store._connect().execute(
            "SELECT status, send_lock_owner, transition_lock_owner"
            " FROM egress_requests WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
        # Status untouched (no stale send lock), current-boot send lock kept,
        # stale transition lock cleared.
        assert row["status"] == "prepared"
        assert row["send_lock_owner"] == send_owner
        assert row["transition_lock_owner"] is None
        rows = _audit_rows(
            str(tmp_path / "psychtool.db"), "egress.transition_lock_recovered"
        )
        assert len(rows) == 1
        assert rows[0]["object_id"] == request.request_id
        assert _audit_rows(
            str(tmp_path / "psychtool.db"), "egress.send_lock_recovered"
        ) == []
    finally:
        egress_send_unlock(case, request.request_id, send_owner)


def test_recovery_skips_row_changed_between_scan_and_update(tmp_path, monkeypatch):
    """The per-row UPDATE is conditional on the observed owners; a row that
    changed in between is skipped with no audit row."""
    store = _make_case(tmp_path)
    case = store.case("case-a")
    config = Config(
        base_url="https://provider.invalid/v1",
        model="model-1",
        data_tier="synthetic",
        api_key="test-key",
    )
    request = prepare_egress_request(
        case,
        prompt="Safe synthetic prompt.",
        purpose="draft_generation",
        config=config,
        source_refs=[],
    )
    store._connect().execute(
        "UPDATE egress_requests SET send_lock_owner = 'FOREIGNBOOT:1:aa'"
        " WHERE request_id = ?",
        (request.request_id,),
    )

    # Between the scan and the transaction, a third writer changes the owner.
    original_transaction = store.transaction

    import contextlib

    @contextlib.contextmanager
    def racing_transaction():
        with contextlib.ExitStack() as stack:
            connection = stack.enter_context(original_transaction())
            connection.execute(
                "UPDATE egress_requests SET send_lock_owner = 'OTHER:2:bb'"
                " WHERE request_id = ?",
                (request.request_id,),
            )
            yield connection

    monkeypatch.setattr(store, "transaction", racing_transaction)
    recovered = recover_stale_send_locks(store, BOOT_ID)
    assert recovered == []
    monkeypatch.setattr(store, "transaction", original_transaction)
    row = store._connect().execute(
        "SELECT send_lock_owner FROM egress_requests WHERE request_id = ?",
        (request.request_id,),
    ).fetchone()
    assert row["send_lock_owner"] == "OTHER:2:bb"  # not clobbered
    assert _audit_rows(
        str(tmp_path / "psychtool.db"), "egress.send_lock_recovered"
    ) == []


# -- (d) idempotency --------------------------------------------------------------


def test_recovery_is_idempotent(tmp_path):
    store = _make_case(tmp_path)
    db = _run_child_until_locked(tmp_path, mode="locked")

    restarted = SqliteStore(db)
    first = recover_stale_send_locks(restarted, BOOT_ID)
    assert len(first) == 1
    second = recover_stale_send_locks(restarted, BOOT_ID)
    assert second == []
    # Still exactly one audit row.
    assert len(_audit_rows(db, "egress.send_lock_recovered")) == 1
