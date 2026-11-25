"""S4/S6 startup self-check tests: cloud-sync detector, disk-encryption
probe (subprocess mocked), and the self-check log lines."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from psychtool.server import selfcheck
from psychtool.server.selfcheck import (
    DataDirError,
    check_data_dir_not_synced,
    cloud_sync_root,
    detect_disk_encryption,
    run_self_checks,
)
from psychtool.store.recovery import BOOT_ID
from psychtool.store.sqlite_store import SqliteStore


# -- cloud-sync detector -----------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/home/u/Dropbox/cases", "dropbox"),
        ("/home/u/dropbox/cases", "dropbox"),
        ("/home/u/OneDrive/cases", "onedrive"),
        ("/home/u/OneDrive - Contoso/cases", "onedrive"),
        ("/home/u/Google Drive/cases", "google drive"),
        ("/home/u/GoogleDrive/cases", "googledrive"),
        ("/home/u/My Drive/cases", "my drive"),
        ("/home/u/iCloud Drive/cases", "icloud drive"),
        ("/Users/u/Library/Mobile Documents/cases", "mobile documents"),
        # The earlier "Mobile Documents" component matches first; same iCloud kind.
        ("/Users/u/Library/Mobile Documents/com~apple~CloudDocs/cases", "mobile documents"),
        ("/Users/u/Library/CloudStorage/Dropbox/cases", "library/cloudstorage"),
        ("/home/u/Box/cases", "box"),
        ("/home/u/Box Sync/cases", "box sync"),
        ("/home/u/pCloud Drive/cases", "pcloud drive"),
        ("/home/u/Sync/cases", "sync"),
        ("/home/u/MEGA/cases", "mega"),
        ("/home/u/data/MEGA", "mega"),
    ],
)
def test_cloud_sync_detector_positive(path, expected):
    assert cloud_sync_root(Path(path)) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/home/u/Dropboxed-notes/cases",  # longer word, NOT Dropbox
        "/home/u/data/cases",
        "/home/u/boxing/cases",
        "/home/u/syncro/cases",
        "/home/u/onedrive-notes/cases",
        "/home/u/my driver/cases",
        "/home/u/Library/CloudStorageExtra/cases",
        "/var/lib/psychtool",
    ],
)
def test_cloud_sync_detector_negative(path):
    assert cloud_sync_root(Path(path)) is None


def test_check_data_dir_refuses_synced_dir(tmp_path):
    synced = tmp_path / "Dropbox" / "cases"
    with pytest.raises(DataDirError) as excinfo:
        check_data_dir_not_synced(synced / "psychtool.db")
    message = str(excinfo.value)
    assert "dropbox" in message.lower()
    assert "psychtool.db" not in message  # names the folder kind, not the file


def test_check_data_dir_allows_local_dir(tmp_path):
    check_data_dir_not_synced(tmp_path / "psychtool.db")  # no raise


# -- disk encryption (subprocess mocked) --------------------------------------


def test_disk_encryption_macos_filevault_on(monkeypatch):
    monkeypatch.setattr(selfcheck.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        selfcheck.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="FileVault is On.\n", stderr=""),
    )
    assert detect_disk_encryption("/tmp/x.db") == "encrypted"


def test_disk_encryption_macos_filevault_off(monkeypatch):
    monkeypatch.setattr(selfcheck.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        selfcheck.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="FileVault is Off.\n", stderr=""),
    )
    assert detect_disk_encryption("/tmp/x.db") == "not-encrypted"


def test_disk_encryption_linux_dm_crypt(monkeypatch, tmp_path):
    mount = tmp_path / "mnt"
    db = mount / "case.db"
    mount.mkdir()
    db.touch()
    mounts = f"/dev/dm-0 {mount} ext4 rw 0 0\n"
    real_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        if str(self) == "/proc/mounts":
            return mounts
        if str(self) == "/sys/block/dm-0/dm/uuid":
            return "CRYPT-LUKS2-abc\n"
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    assert selfcheck._linux_disk_encryption(db) == "encrypted"


def test_disk_encryption_linux_plain_device(monkeypatch, tmp_path):
    mount = tmp_path / "mnt"
    db = mount / "case.db"
    mount.mkdir()
    db.touch()
    mounts = f"/dev/sda1 {mount} ext4 rw 0 0\n"
    real_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        if str(self) == "/proc/mounts":
            return mounts
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    assert selfcheck._linux_disk_encryption(db) == "not-encrypted"


def test_disk_encryption_windows_protection_on(monkeypatch):
    monkeypatch.setattr(selfcheck.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        selfcheck.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout="Conversion Status: Fully Encrypted\nProtection Status: Protection On\n",
            stderr="",
        ),
    )
    assert detect_disk_encryption("C:/x.db") == "encrypted"


def test_disk_encryption_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(selfcheck.platform, "system", lambda: "Darwin")

    def boom(*a, **k):
        raise FileNotFoundError("fdesetup missing")

    monkeypatch.setattr(selfcheck.subprocess, "run", boom)
    assert detect_disk_encryption("/tmp/x.db") == "unknown"


def test_disk_encryption_unknown_platform(monkeypatch):
    monkeypatch.setattr(selfcheck.platform, "system", lambda: "Plan9")
    assert detect_disk_encryption("/tmp/x.db") == "unknown"


# -- run_self_checks ----------------------------------------------------------


def test_run_self_checks_logs_one_line_each(tmp_path, caplog):
    store = SqliteStore(tmp_path / "psychtool.db")
    with caplog.at_level(logging.INFO, logger="psychtool"):
        results = run_self_checks(store, host="127.0.0.1", token_source="generated")
    names = [r.name for r in results]
    assert names == [
        "bind",
        "token",
        "host-check",
        "csp",
        "data-dir",
        "disk-encryption",
        "audit-chain",
        "send-lock-recovery",
    ]
    messages = [r.getMessage() for r in caplog.records if "self-check" in r.getMessage()]
    assert len(messages) == len(results)
    assert any("bind 127.0.0.1" in m for m in messages)
    assert any("session token: generated (not shown)" in m for m in messages)
    assert any("audit chain verified (0 entries)" in m for m in messages)
    assert any("stale send-lock recovery: 0 recovered" in m for m in messages)


def test_run_self_checks_refuses_synced_data_dir(tmp_path):
    synced = tmp_path / "Dropbox" / "data"
    synced.mkdir(parents=True)
    store = SqliteStore(synced / "psychtool.db")
    with pytest.raises(DataDirError):
        run_self_checks(store, host="127.0.0.1", token_source="generated")


def test_run_self_checks_broken_chain_is_loud_but_not_fatal(tmp_path, caplog):
    import sqlite3

    db = tmp_path / "psychtool.db"
    store = SqliteStore(db)
    store.create_case("case-a")
    # Tamper: drop the trigger in a raw connection and alter one row.
    raw = sqlite3.connect(db)
    raw.execute("DROP TRIGGER audit_log_no_update")
    raw.execute("UPDATE audit_log SET action = 'forged' WHERE seq = 1")
    raw.commit()
    raw.close()
    with caplog.at_level(logging.INFO, logger="psychtool"):
        results = run_self_checks(store, host="127.0.0.1", token_source="generated")
    chain = next(r for r in results if r.name == "audit-chain")
    assert chain.status == "error"
    assert "seq 1" in chain.detail
    assert any("AUDIT CHAIN BROKEN" in r.getMessage() for r in caplog.records)
