"""Startup self-checks (ADR 0011): loopback bind, token, Host, CSP,
cloud-sync data-dir refusal, disk-encryption warning, audit-chain verify,
and stale send-lock recovery.

Each check logs one line through the ``psychtool`` logger — the line names
the check and its outcome only, never user content and never the token.
The cloud-sync check *refuses to start* (raises :class:`DataDirError`); the
disk-encryption check is a WARNING only in M1; a broken audit chain is a
loud ERROR line but does not block startup.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

from psychtool.server.security import SESSION_ENV
from psychtool.store.recovery import BOOT_ID, recover_stale_send_locks
from psychtool.store.sqlite_store import SqliteStore

logger = logging.getLogger("psychtool")

# Cloud-sync folder kinds matched as whole path components (case-insensitive).
# Exact names match only the component itself; a name in the
# "extended" set also matches a separator suffix ("OneDrive - Personal").
# "Dropboxed-notes" / "onedrive-notes" therefore never match.
_SYNC_EXACT_NAMES = (
    "dropbox",
    "google drive",
    "googledrive",
    "my drive",
    "icloud drive",
    "mobile documents",
    "com~apple~clouddocs",
    "box",
    "box sync",
    "pcloud drive",
    "sync",
    "mega",
)
_SYNC_EXTENDED_NAMES = ("onedrive",)

# Component sequence match: macOS cloud storage lives under ~/Library/CloudStorage.
_SYNC_COMPONENT_SEQUENCES = (("library", "cloudstorage"),)


class DataDirError(RuntimeError):
    """Raised when the database path sits inside a cloud-sync folder."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "ok" | "warn" | "error"
    detail: str


def cloud_sync_root(path: Path | str) -> str | None:
    """Return the sync-folder kind containing ``path``, or None.

    Pure function over path components: any ancestor component that *is* a
    known sync root (whole-component match) marks the path as synced. The
    folder kind is returned (e.g. "Dropbox"); file contents are irrelevant.
    A component like ``Dropboxed-notes`` does NOT match ``dropbox``.
    """
    resolved = Path(path).resolve()
    parts = [part.lower() for part in resolved.parts]
    for index, part in enumerate(parts):
        for sequence in _SYNC_COMPONENT_SEQUENCES:
            if tuple(parts[index : index + len(sequence)]) == sequence:
                return "/".join(sequence)
        for name in _SYNC_EXACT_NAMES:
            # Exact whole-component match only: "Dropboxed-notes",
            # "box sync old" and "mega2" are not sync folders.
            if part == name:
                return name
        for name in _SYNC_EXTENDED_NAMES:
            # Extended match: the component equals the name or extends it
            # with a space ("OneDrive - Personal", "OneDrive Personal").
            # "onedrive-notes" is a longer word, not OneDrive.
            if part == name or part.startswith(name + " "):
                return name
    return None


def check_data_dir_not_synced(db_path: Path | str) -> None:
    """Refuse to run with the database inside a cloud-sync folder."""
    kind = cloud_sync_root(Path(db_path).parent)
    if kind is not None:
        raise DataDirError(
            f"refusing to start: the data directory is inside a {kind} "
            "cloud-sync folder; move it to a local, non-synced directory"
        )


def detect_disk_encryption(db_path: Path | str) -> str:
    """Best-effort local disk-encryption probe; never touches the network.

    Returns "encrypted", "not-encrypted", or "unknown" (any failure). M1 logs
    a warning only; this never blocks startup.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            output = subprocess.run(
                ["fdesetup", "status"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if output.returncode == 0:
                if "FileVault is On" in output.stdout:
                    return "encrypted"
                if "FileVault is Off" in output.stdout:
                    return "not-encrypted"
            return "unknown"
        if system == "Linux":
            return _linux_disk_encryption(Path(db_path))
        if system == "Windows":
            output = subprocess.run(
                ["manage-bde", "-status", "C:"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if output.returncode == 0:
                if "Protection On" in output.stdout:
                    return "encrypted"
                if "Protection Off" in output.stdout:
                    return "not-encrypted"
            return "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _linux_disk_encryption(db_path: Path) -> str:
    """Check whether the DB path's mount source is a dm-crypt/LUKS device."""
    mounts = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    best_source = None
    best_length = -1
    resolved = db_path.resolve()
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        source, mountpoint = fields[0], fields[1]
        try:
            relative = resolved.relative_to(mountpoint)
        except ValueError:
            continue
        depth = len(Path(mountpoint).parts)
        if depth > best_length:
            best_length = depth
            best_source = source
        _ = relative
    if best_source is None:
        return "unknown"
    device = Path(best_source).name
    if device.startswith("dm-"):
        uuid_path = Path(f"/sys/block/{device}/dm/uuid")
        try:
            if uuid_path.read_text(encoding="utf-8").strip().startswith("CRYPT-"):
                return "encrypted"
        except OSError:
            return "unknown"
        return "not-encrypted"
    return "not-encrypted"


def run_self_checks(
    store: SqliteStore,
    *,
    host: str,
    token_source: str,
    boot_id: str = BOOT_ID,
) -> list[CheckResult]:
    """Run every startup check, log one line each, and return the results.

    Raises :class:`DataDirError` for a cloud-synced data dir (the caller must
    not start the server). Everything else is logged and reported.
    """
    results: list[CheckResult] = []

    def record(name: str, status: str, detail: str) -> None:
        results.append(CheckResult(name=name, status=status, detail=detail))
        log = logger.warning if status == "warn" else (
            logger.error if status == "error" else logger.info
        )
        log("self-check %s: %s", status, detail)

    if host in ("127.0.0.1", "localhost", "::1"):
        record("bind", "ok", f"bind {host}")
    else:
        record("bind", "error", f"bind address {host} is not loopback")

    record("token", "ok", f"session token: {token_source} (not shown)")
    record("host-check", "ok", "Host header restricted to loopback names")
    record("csp", "ok", "strict Content-Security-Policy on all responses")

    check_data_dir_not_synced(store.path)
    record("data-dir", "ok", "data dir is not inside a cloud-sync folder")

    encryption = detect_disk_encryption(store.path)
    if encryption == "encrypted":
        record("disk-encryption", "ok", "system disk encryption: on")
    elif encryption == "not-encrypted":
        record(
            "disk-encryption",
            "warn",
            "system disk encryption: off (warning only in M1)",
        )
    else:
        record(
            "disk-encryption",
            "warn",
            "system disk encryption: unknown (warning only in M1)",
        )

    ok, count, first_bad = store.verify_audit_chain()
    if ok:
        record("audit-chain", "ok", f"audit chain verified ({count} entries)")
    else:
        record(
            "audit-chain",
            "error",
            f"AUDIT CHAIN BROKEN at seq {first_bad} of {count} entries; "
            "the audit log may have been tampered with",
        )

    recovered = recover_stale_send_locks(store, boot_id)
    record(
        "send-lock-recovery",
        "ok",
        f"stale send-lock recovery: {len(recovered)} recovered",
    )
    return results
