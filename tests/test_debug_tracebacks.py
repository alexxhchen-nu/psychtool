"""ADR 0013: the dev-only debug-tracebacks switch and the v3->v4 schema step.

The switch (``PSYCHTOOL_DEBUG_TRACEBACKS=1``) is honoured only for the
synthetic tier: ``main`` refuses to start with the real tier, ``create_app``
forces tracebacks off for the real tier regardless of the env, and the
default (off) behavior — fixed 500 body, type-only log line — is unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3

import pytest

from psychtool.config import Config, debug_tracebacks_enabled, load_config
from psychtool.core.workspace import Passage
from psychtool.server.app import create_app
from psychtool.store.sqlite_store import _SCHEMA_VERSION, SqliteStore
from psychtool.store.audit import verify_audit_chain
from tests.conftest import build_client

MARKER = "ZEBRA-DEBUG-MARKER-77f1"


# -- the decider ---------------------------------------------------------------


def test_debug_tracebacks_enabled_matrix(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DEBUG_TRACEBACKS", "1")
    assert debug_tracebacks_enabled(Config(data_tier="synthetic",
                                           debug_tracebacks=True)) is True
    # Real tier: never, even with env=1 and the flag set.
    assert debug_tracebacks_enabled(Config(data_tier="real",
                                           debug_tracebacks=True)) is False
    # Flag not set on the config: env alone is not enough.
    assert debug_tracebacks_enabled(Config(data_tier="synthetic")) is False
    monkeypatch.setenv("PSYCHTOOL_DEBUG_TRACEBACKS", "true")
    assert debug_tracebacks_enabled(Config(data_tier="synthetic",
                                           debug_tracebacks=True)) is False
    monkeypatch.setenv("PSYCHTOOL_DEBUG_TRACEBACKS", "yes")
    assert debug_tracebacks_enabled(Config(data_tier="synthetic",
                                           debug_tracebacks=True)) is False
    monkeypatch.delenv("PSYCHTOOL_DEBUG_TRACEBACKS")
    assert debug_tracebacks_enabled(Config(data_tier="synthetic",
                                           debug_tracebacks=True)) is False


def test_load_config_real_tier_never_enables_tracebacks(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DEBUG_TRACEBACKS", "1")
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "real")
    config = load_config()
    assert config.data_tier == "real"
    assert config.debug_tracebacks is False
    assert debug_tracebacks_enabled(config) is False
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "synthetic")
    config = load_config()
    assert config.debug_tracebacks is True
    assert debug_tracebacks_enabled(config) is True
    monkeypatch.delenv("PSYCHTOOL_DEBUG_TRACEBACKS")
    assert load_config().debug_tracebacks is False


# -- main() startup decisions ---------------------------------------------------


def test_main_refuses_real_tier_with_debug_tracebacks(monkeypatch, tmp_path, capsys):
    import psychtool.server.main as main_module

    monkeypatch.setenv("PSYCHTOOL_DEBUG_TRACEBACKS", "1")
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "real")
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run",
                        lambda *a, **k: calls.append((a, k)))
    with pytest.raises(SystemExit) as excinfo:
        main_module.main()
    assert excinfo.value.code == 2
    assert calls == []
    stderr = capsys.readouterr().err
    assert "PSYCHTOOL_DEBUG_TRACEBACKS" in stderr
    assert "real" in stderr


def test_main_synthetic_debug_skips_filter_and_warns(monkeypatch, tmp_path, caplog):
    import psychtool.server.main as main_module

    monkeypatch.setenv("PSYCHTOOL_DEBUG_TRACEBACKS", "1")
    monkeypatch.delenv("PSYCHTOOL_DATA_TIER", raising=False)
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run",
                        lambda *a, **k: calls.append(k))
    with caplog.at_level(logging.WARNING, logger="psychtool"):
        main_module.main()
    assert len(calls) == 1
    assert calls[0]["log_config"] is None
    assert any(
        "self-check warn: debug tracebacks ON (dev only; never with real data)"
        in record.getMessage()
        for record in caplog.records
    )


def test_main_default_keeps_type_only_filter(monkeypatch, tmp_path):
    import psychtool.server.main as main_module

    monkeypatch.delenv("PSYCHTOOL_DEBUG_TRACEBACKS", raising=False)
    monkeypatch.delenv("PSYCHTOOL_DATA_TIER", raising=False)
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run",
                        lambda *a, **k: calls.append(k))
    main_module.main()
    assert len(calls) == 1
    assert calls[0]["log_config"] is not None
    filters = calls[0]["log_config"]["filters"]
    assert "psychtool_type_only_errors" in filters


# -- catch-all behavior in create_app -------------------------------------------


def _raising_client(tmp_path, monkeypatch, *, debug: bool, tier="synthetic"):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", tier)
    if debug:
        monkeypatch.setenv("PSYCHTOOL_DEBUG_TRACEBACKS", "1")
    else:
        monkeypatch.delenv("PSYCHTOOL_DEBUG_TRACEBACKS", raising=False)
    app = create_app()

    @app.get("/api/workspaces/{case_id}/boom")
    def boom(case_id: str):  # pragma: no cover - trivially raises
        _ = case_id
        raise RuntimeError(f"{MARKER} secret text")

    app.routes.insert(0, app.routes.pop())
    return build_client(app, raise_server_exceptions=False)


def test_catch_all_logs_full_traceback_when_debug_on(tmp_path, monkeypatch, caplog):
    client = _raising_client(tmp_path, monkeypatch, debug=True)
    with caplog.at_level(logging.DEBUG, logger="psychtool"):
        response = client.get("/api/workspaces/case-a/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal error"}
    own = [r for r in caplog.records if r.name == "psychtool"]
    assert any("debug tracebacks ON" in r.getMessage() for r in own)
    assert any(r.exc_info for r in own)


def test_catch_all_stays_type_only_for_real_tier_even_with_env(
    tmp_path, monkeypatch, caplog
):
    client = _raising_client(tmp_path, monkeypatch, debug=True, tier="real")
    with caplog.at_level(logging.DEBUG, logger="psychtool"):
        response = client.get("/api/workspaces/case-a/boom")
    assert response.status_code == 500
    own = [r for r in caplog.records
           if r.name == "psychtool" and r.getMessage().startswith("unhandled")]
    assert [r.getMessage() for r in own] == ["unhandled error: RuntimeError"]
    assert not any(r.exc_info for r in own)
    for record in caplog.records:
        assert MARKER not in record.getMessage()


def test_catch_all_default_unchanged(tmp_path, monkeypatch, caplog):
    client = _raising_client(tmp_path, monkeypatch, debug=False)
    with caplog.at_level(logging.DEBUG, logger="psychtool"):
        response = client.get("/api/workspaces/case-a/boom")
    assert response.status_code == 500
    own = [r for r in caplog.records
           if r.name == "psychtool" and r.getMessage().startswith("unhandled")]
    assert [r.getMessage() for r in own] == ["unhandled error: RuntimeError"]


# -- real uvicorn subprocess -----------------------------------------------------


def _run_boom_subprocess(tmp_path, monkeypatch, *, debug: bool):
    import os
    import socket
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env_token = "d" * 40
    script = (
        "from psychtool.server.app import create_app\n"
        "from psychtool.server.main import _uvicorn_log_config\n"
        "import uvicorn\n"
        "app = create_app()\n"
        "@app.get('/api/workspaces/{case_id}/boom')\n"
        "def boom(case_id: str):\n"
        f"    raise RuntimeError({MARKER!r} + ' secret text')\n"
        "app.routes.insert(0, app.routes.pop())\n"
        "uvicorn.run(app, host='127.0.0.1', port="
        + str(port)
        + (", log_config=None" if debug else ", log_config=_uvicorn_log_config()")
        + ")\n"
    )
    env = dict(os.environ)
    env["PSYCHTOOL_DB_PATH"] = str(tmp_path / "psychtool.db")
    env["PSYCHTOOL_SESSION_TOKEN"] = env_token
    env["PSYCHTOOL_DATA_TIER"] = "synthetic"
    if debug:
        env["PSYCHTOOL_DEBUG_TRACEBACKS"] = "1"
    else:
        env.pop("PSYCHTOOL_DEBUG_TRACEBACKS", None)
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=2
                ) as health:
                    assert health.status == 200
                break
            except Exception:
                time.sleep(0.2)
        else:  # pragma: no cover - server never came up
            raise AssertionError("uvicorn subprocess did not start")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/workspaces/case-a/boom",
            headers={"X-Psychtool-Token": env_token},
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("boom route unexpectedly succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 500
    finally:
        process.kill()
        _, stderr = process.communicate(timeout=10)
    return stderr


def test_subprocess_debug_on_shows_traceback(tmp_path, monkeypatch):
    stderr = _run_boom_subprocess(tmp_path, monkeypatch, debug=True)
    assert "unhandled error (debug tracebacks ON)" in stderr
    assert MARKER in stderr
    assert "Traceback" in stderr


def test_subprocess_default_env_hides_traceback(tmp_path, monkeypatch):
    stderr = _run_boom_subprocess(tmp_path, monkeypatch, debug=False)
    assert "unhandled error: RuntimeError" in stderr
    assert MARKER not in stderr
    assert "Traceback" not in stderr


# -- schema v3 -> v4 ------------------------------------------------------------


def _build_v3_database(db_path):
    """A genuine v3 database: current v3 schema, no item_count column."""
    store = SqliteStore(db_path)
    store.create_case("case-old")
    raw = sqlite3.connect(db_path)
    raw.execute("ALTER TABLE audit_log RENAME TO audit_log_v4")
    raw.execute(
        "CREATE TABLE audit_log ("
        " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        " case_id TEXT, ts TEXT NOT NULL, action TEXT NOT NULL,"
        " object_type TEXT NOT NULL, object_id TEXT NOT NULL,"
        " content_hash TEXT, destination TEXT,"
        " prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL)"
    )
    raw.execute(
        "INSERT INTO audit_log"
        " (case_id, ts, action, object_type, object_id, content_hash,"
        "  destination, prev_hash, entry_hash)"
        " SELECT case_id, ts, action, object_type, object_id, content_hash,"
        "  destination, prev_hash, entry_hash FROM audit_log_v4"
    )
    raw.execute("DROP TABLE audit_log_v4")
    # Recreate the append-only triggers on the rebuilt table.
    raw.execute(
        "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log"
        " BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
    )
    raw.execute(
        "CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log"
        " BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
    )
    raw.execute("PRAGMA user_version = 3")
    raw.commit()
    raw.close()


def test_v3_database_migrates_to_v4_and_chain_verifies(tmp_path):
    db = tmp_path / "psychtool.db"
    _build_v3_database(db)
    store = SqliteStore(db)  # opening runs the v3->v4 migration
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(audit_log)")}
    assert "item_count" in columns
    # Pre-v4 rows keep NULL item_count and their original hashes verify.
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 1, None)
    row = connection.execute(
        "SELECT item_count FROM audit_log WHERE seq = 1"
    ).fetchone()
    assert row["item_count"] is None


def test_item_count_tampering_is_detected(tmp_path):
    db = tmp_path / "psychtool.db"
    store = SqliteStore(db)
    store.create_case("case-a")
    case = store.case("case-a")
    case.import_material(
        material_id="doc-1", title="Synthetic",
        provider="synthetic", date="synthetic date",
        passages=[Passage(id="p001", text="Synthetic.")],
        blocked_count=2,
        blocked_hash=hashlib.sha256(b"x").hexdigest(),
    )
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 3, None)

    raw = sqlite3.connect(db)
    raw.execute("DROP TRIGGER audit_log_no_update")
    raw.execute(
        "UPDATE audit_log SET item_count = 99"
        " WHERE action = 'material.protected_blocked'"
    )
    raw.commit()
    raw.close()
    ok, _, bad = verify_audit_chain(store)
    assert ok is False
    assert bad is not None


def test_item_count_rejects_negative_bool_and_str(tmp_path):
    store = SqliteStore(tmp_path / "psychtool.db")
    store.create_case("case-a")
    for bad_value in (-1, True, "3", 1.5):
        with pytest.raises(ValueError):
            store.append_audit(
                case_id="case-a",
                action="material.protected_blocked",
                object_type="material",
                object_id="doc-1",
                content_hash=hashlib.sha256(b"x").hexdigest(),
                item_count=bad_value,
            )
