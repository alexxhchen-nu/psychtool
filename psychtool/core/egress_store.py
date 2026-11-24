"""Storage seam for the egress gateway and its safety state machine.

The prepare -> approve -> send pipeline (approval-hash check, send-once
guarantee, data-tier/network refusal, stale-source invalidation, output PII
gate) is implemented exactly once in :mod:`psychtool.core.egress` and
:mod:`psychtool.gateway.client`. Both stores the app supports satisfy this
protocol, so the safety logic never forks per store:

- :class:`JsonDirStore` adapts the ADR 0005 JSON workspace directory (legacy
  CLI/TUI path);
- :class:`SqliteGatewayStore` adapts one case inside the SQLite database
  (ADR 0010 browser/server path).

Locking: both stores expose a per-request transition lock with identical
semantics (in-process mutex + fail-closed on-disk/in-row lock marker). The
SQLite store additionally enforces send-once with a conditional UPDATE whose
outcome is decided by the database, not by a prior read.

This module must not import ``psychtool.core.egress`` at module level (the
egress module imports this one); egress helpers are imported lazily inside
functions.
"""

from __future__ import annotations

import json
import secrets
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.core.egress import EgressRequest

_EGRESS_DIR_NAME = "egress"


def _validate_request_id(request_id: str) -> str:
    from psychtool.core.egress import _validate_request_id as _validate

    return _validate(request_id)


def _state_error(message: str):
    from psychtool.core.egress import EgressStateError

    return EgressStateError(message)


class EgressStore(Protocol):
    """Persistence the egress pipeline needs from either backend."""

    @property
    def case_id(self) -> str:
        """The case/workspace id that egress requests are filed under."""
        ...

    def get_known_names(self) -> tuple[str, ...]: ...

    def save_egress_request(self, request: EgressRequest) -> None: ...

    def get_egress_request(self, request_id: str) -> EgressRequest: ...

    def request_lock_key(self, request_id: str) -> str:
        """Stable, process-wide key identifying one request's transition lock."""
        ...

    def try_acquire_transition_lock(self, request_id: str, owner: str) -> bool: ...

    def release_transition_lock(self, request_id: str, owner: str) -> None: ...

    def try_acquire_send_lock(self, request_id: str, owner: str) -> bool: ...

    def release_send_lock(self, request_id: str, owner: str) -> None: ...


class JsonDirStore:
    """ADR 0005 JSON workspace directory behind the egress store protocol."""

    def __init__(self, workspace: Path | str) -> None:
        self._workspace = Path(workspace)

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def case_id(self) -> str:
        meta = json.loads((self._workspace / "meta.json").read_text(encoding="utf-8"))
        return meta["case_id"]

    def get_known_names(self) -> tuple[str, ...]:
        from psychtool.core.workspace import get_known_names

        return get_known_names(self._workspace)

    def save_egress_request(self, request: EgressRequest) -> None:
        # Imported lazily to avoid a module cycle (egress imports this module).
        from psychtool.core.egress import save_egress_request

        save_egress_request(self._workspace, request)

    def get_egress_request(self, request_id: str) -> EgressRequest:
        from psychtool.core.egress import get_egress_request

        return get_egress_request(self._workspace, request_id)

    def _egress_dir(self) -> Path:
        directory = self._workspace / _EGRESS_DIR_NAME
        directory.mkdir(exist_ok=True)
        return directory

    def request_lock_key(self, request_id: str) -> str:
        request_id = _validate_request_id(request_id)
        return str((self._egress_dir() / f".{request_id}.transition.lock").resolve())

    def try_acquire_transition_lock(self, request_id: str, owner: str) -> bool:
        import os

        request_id = _validate_request_id(request_id)
        lock_path = self._egress_dir() / f".{request_id}.transition.lock"
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(descriptor, mode="w", encoding="ascii") as lock_file:
            lock_file.write(owner)
            lock_file.flush()
            os.fsync(lock_file.fileno())
        return True

    def release_transition_lock(self, request_id: str, owner: str) -> None:
        request_id = _validate_request_id(request_id)
        lock_path = self._egress_dir() / f".{request_id}.transition.lock"
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
                raise _state_error(
                    "egress request transition cleanup failed"
                ) from None

    def try_acquire_send_lock(self, request_id: str, owner: str) -> bool:
        import os

        request_id = _validate_request_id(request_id)
        lock_path = self._egress_dir() / f"{request_id}.send.lock"
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        try:
            with os.fdopen(descriptor, mode="w", encoding="ascii") as lock_file:
                lock_file.write(owner)
                lock_file.flush()
                os.fsync(lock_file.fileno())
        except BaseException:
            self.release_send_lock(request_id, owner)
            raise
        return True

    def release_send_lock(self, request_id: str, owner: str) -> None:
        request_id = _validate_request_id(request_id)
        lock_path = self._egress_dir() / f"{request_id}.send.lock"
        try:
            current_owner = lock_path.read_text(encoding="ascii")
        except (FileNotFoundError, OSError, UnicodeError):
            return
        if current_owner == owner:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


class SqliteGatewayStore:
    """One case inside the SQLite database behind the egress store protocol."""

    def __init__(self, case_store) -> None:
        self._case = case_store

    def get_known_names(self) -> tuple[str, ...]:
        return self._case.get_known_names()

    def save_egress_request(self, request: EgressRequest) -> None:
        if request.workspace_id != self._case.case_id:
            raise _state_error("egress request belongs to a different case")
        self._case.save_egress_request(request)

    def get_egress_request(self, request_id: str) -> EgressRequest:
        return self._case.get_egress_request(request_id)

    def request_lock_key(self, request_id: str) -> str:
        request_id = _validate_request_id(request_id)
        return f"sqlite:{self._case._store.path}:{self._case.case_id}:{request_id}"

    def try_acquire_transition_lock(self, request_id: str, owner: str) -> bool:
        return self._case.try_acquire_transition_lock(request_id, owner)

    def release_transition_lock(self, request_id: str, owner: str) -> None:
        self._case.release_transition_lock(request_id, owner)

    def try_acquire_send_lock(self, request_id: str, owner: str) -> bool:
        return self._case.try_acquire_send_lock(request_id, owner)

    def release_send_lock(self, request_id: str, owner: str) -> None:
        self._case.release_send_lock(request_id, owner)


# One mutex per lock key per process; the store-specific marker (lock file or
# DB column) provides the cross-process / crash-persistent half.
_MUTEXES: dict[str, threading.Lock] = {}
_MUTEXES_GUARD = threading.Lock()


@contextmanager
def egress_transition_lock(store: EgressStore, request_id: str) -> Iterator[None]:
    """Serialize one request's transitions and leave crash-created locks closed."""
    key = store.request_lock_key(request_id)
    with _MUTEXES_GUARD:
        mutex = _MUTEXES.setdefault(key, threading.Lock())

    owner = secrets.token_hex(32)
    acquired = False
    mutex.acquire()
    try:
        if not store.try_acquire_transition_lock(request_id, owner):
            raise _state_error("egress request transition is locked")
        acquired = True
        yield
    finally:
        try:
            if acquired:
                store.release_transition_lock(request_id, owner)
        finally:
            mutex.release()


def egress_send_lock(store: EgressStore, request_id: str) -> tuple[str, str]:
    """Acquire the send-once lock; returns (lock_key, owner) on success."""
    owner = secrets.token_hex(32)
    if not store.try_acquire_send_lock(request_id, owner):
        raise _state_error("egress request send is locked")
    return store.request_lock_key(request_id), owner


def egress_send_unlock(store: EgressStore, request_id: str, owner: str) -> None:
    store.release_send_lock(request_id, owner)
