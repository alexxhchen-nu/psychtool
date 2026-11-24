"""Crash recovery for egress send/transition locks (fail-closed, ADR 0011).

A crash between taking the SQLite send lock and releasing it used to leave
the request stuck forever. The lock owner now names the process
(``boot_id:pid:random``); at startup every lock whose boot id is not the
current process's boot id is *stale* and is recovered:

- status ``sent``: the send finished, only the unlock was lost — clear the
  lock, keep the status;
- any other status: we cannot know whether the transport delivered, so the
  request is marked ``send_interrupted`` (terminal — it can never be sent
  again; the user prepares a fresh request with a new request_id).

A stale ``transition_lock_owner`` from the old boot is cleared the same way;
a transition lock owned by the *current* boot is never touched (a live
request in this process may hold it). Every recovery — send lock or
transition lock only — appends one audit row (``egress.send_lock_recovered``
/ ``egress.transition_lock_recovered``) in the same transaction as the state
change. Recovery never allows a second send: the terminal status is what the
send path checks, not the absence of a lock.

Single-writer assumption: the server is the only process writing to the
SQLite case store, so a foreign boot id always means the previous server
process died; there is no live peer to protect.
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.store.sqlite_store import SqliteStore

# Random per-process boot id: a lock written by any earlier process is stale.
BOOT_ID = secrets.token_urlsafe(16)


def make_lock_owner(boot_id: str) -> str:
    """Lock owner naming the owning process: boot id, pid, random nonce."""
    return f"{boot_id}:{os.getpid()}:{secrets.token_hex(16)}"


def _owner_boot_id(owner: str | None) -> str | None:
    if not owner:
        return None
    return owner.split(":", 1)[0]


def recover_stale_send_locks(
    store: "SqliteStore", current_boot_id: str
) -> list[dict]:
    """Recover every lock left by a previous server process.

    Returns one record per recovered request (``request_id``, ``case_id``,
    ``prior_status``). Idempotent: a second run finds no stale locks and
    writes no audit rows.
    """
    connection = store._connect()
    rows = connection.execute(
        "SELECT case_id, request_id, status, content_hash,"
        "       send_lock_owner, transition_lock_owner"
        " FROM egress_requests"
        " WHERE send_lock_owner IS NOT NULL OR transition_lock_owner IS NOT NULL"
    ).fetchall()
    recovered: list[dict] = []
    for row in rows:
        send_boot = _owner_boot_id(row["send_lock_owner"])
        transition_boot = _owner_boot_id(row["transition_lock_owner"])
        send_stale = (
            row["send_lock_owner"] is not None and send_boot != current_boot_id
        )
        transition_stale = (
            row["transition_lock_owner"] is not None
            and transition_boot != current_boot_id
        )
        if not send_stale and not transition_stale:
            continue
        with store.transaction() as transaction:
            # Re-read inside the transaction and make the UPDATE conditional
            # on the owners we observed: if another writer changed the row
            # between the scan and the transaction, skip instead of
            # clobbering a lock we did not verify.
            current = transaction.execute(
                "SELECT status, send_lock_owner, transition_lock_owner"
                " FROM egress_requests WHERE case_id = ? AND request_id = ?",
                (row["case_id"], row["request_id"]),
            ).fetchone()
            if current is None:
                continue
            interrupted = (
                send_stale and current["status"] != "sent"
            )
            if interrupted:
                cursor = transaction.execute(
                    "UPDATE egress_requests SET status = 'send_interrupted',"
                    " send_lock_owner = NULL, transition_lock_owner = NULL"
                    " WHERE case_id = ? AND request_id = ?"
                    " AND send_lock_owner IS ? AND transition_lock_owner IS ?",
                    (
                        row["case_id"],
                        row["request_id"],
                        row["send_lock_owner"],
                        row["transition_lock_owner"],
                    ),
                )
            else:
                # Clear only the stale owners; a current-boot transition lock
                # stays in place.
                new_send = None if send_stale else row["send_lock_owner"]
                new_transition = (
                    None if transition_stale else row["transition_lock_owner"]
                )
                cursor = transaction.execute(
                    "UPDATE egress_requests SET send_lock_owner = ?,"
                    " transition_lock_owner = ?"
                    " WHERE case_id = ? AND request_id = ?"
                    " AND send_lock_owner IS ? AND transition_lock_owner IS ?",
                    (
                        new_send,
                        new_transition,
                        row["case_id"],
                        row["request_id"],
                        row["send_lock_owner"],
                        row["transition_lock_owner"],
                    ),
                )
            if cursor.rowcount == 0:
                continue
            if send_stale:
                # Same transaction as the state change: a crash cannot leave
                # the recovery without its audit row.
                store.append_audit(
                    case_id=row["case_id"],
                    action="egress.send_lock_recovered",
                    object_type="egress_request",
                    object_id=row["request_id"],
                    content_hash=row["content_hash"],
                )
            elif transition_stale:
                store.append_audit(
                    case_id=row["case_id"],
                    action="egress.transition_lock_recovered",
                    object_type="egress_request",
                    object_id=row["request_id"],
                    content_hash=row["content_hash"],
                )
        recovered.append(
            {
                "case_id": row["case_id"],
                "request_id": row["request_id"],
                "prior_status": row["status"],
            }
        )
    return recovered
