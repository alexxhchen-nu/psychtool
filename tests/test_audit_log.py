"""S6 audit-log tests: marker hygiene, append-only triggers, free-text
rejection, tamper detection, restart durability, and v1->v2 migration."""

from __future__ import annotations

import logging
import sqlite3

import pytest

from psychtool.store.audit import (
    AUDIT_ACTIONS,
    GENESIS_PREV_HASH,
    append_audit,
    verify_audit_chain,
)
from psychtool.store.sqlite_store import _SCHEMA_VERSION, SqliteStore

MARKER = "ZEBRA-MARKER-7f3a"


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


def _all_audit_values(store) -> list[str]:
    rows = store._connect().execute("SELECT * FROM audit_log").fetchall()
    return [str(row[column]) for row in rows for column in row.keys()]


# -- (i) marker hygiene across a full flow ------------------------------------


def test_marker_never_reaches_audit_log_logs_or_error_bodies(tmp_path, caplog, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    app_module = importlib.import_module("psychtool.server.app")
    db = tmp_path / "psychtool.db"
    monkeypatch.setattr(app_module, "default_db_path", lambda: db)
    app = app_module.create_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Psychtool-Token": app.state.session_token}

    responses = []
    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers)
        assert response.status_code == 201, response.text
        # Duplicate case -> 4xx with a fixed detail.
        responses.append(
            client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers)
        )
        # Push marker text through the paste-import and section-save paths.
        paste = client.post(
            "/api/workspaces/case-a/materials/paste",
            json={
                "material_id": "paste-1",
                "title": MARKER,
                "provider": MARKER,
                "date": "2026-11-24",
                "text": f"patient says {MARKER}",
                "synthetic_confirmed": True,
            },
            headers=headers,
        )
        assert paste.status_code == 200
        section = client.put(
            "/api/workspaces/case-a/sections/history",
            json={
                "template_id": "intake-report",
                "template_version": 1,
                "text": f"note containing {MARKER}",
            },
            headers=headers,
        )
        assert section.status_code == 200
        # A section save with an unknown template id -> 4xx with a fixed
        # detail (the marker text must not be echoed back).
        responses.append(
            client.put(
                "/api/workspaces/case-a/sections/history",
                json={
                    "template_id": "no-such-template",
                    "template_version": 1,
                    "text": MARKER,
                },
                headers=headers,
            )
        )
        # Unauthorized request carrying the marker in the token header.
        responses.append(
            client.get("/api/workspaces", headers={"X-Psychtool-Token": MARKER})
        )

    store = SqliteStore(db)
    audit_values = _all_audit_values(store)
    assert audit_values, "expected audit rows from the flow"
    for value in audit_values:
        assert MARKER not in value
    for record in caplog.records:
        assert MARKER not in record.getMessage()
    # Error responses only: success payloads legitimately echo the caller's
    # own text back; what must never leak the marker is a failure body.
    for response in responses:
        assert response.status_code >= 400, response.text
        assert MARKER not in response.text, response.text


# -- (ii) append-only triggers on the store's own connection -------------------


def test_update_on_audit_log_raises(store):
    store.create_case("case-a")
    connection = store._connect()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE audit_log SET action = 'forged'")
    connection.rollback()


def test_delete_on_audit_log_raises(store):
    store.create_case("case-a")
    connection = store._connect()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM audit_log")
    connection.rollback()


# -- (iii) writer rejects free text in each field -------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "case hacked"},                     # free text action
        {"action": "note: patient said X"},
        {"object_type": "diary"},                      # unknown object type
        {"object_type": "patient name here"},
        {"object_id": "id with spaces"},
        {"object_id": "Zoe S. said hello"},            # free text id
        {"object_id": ""},
        {"object_id": "x" * 200},                      # too long
        {"object_id": ".leading-dot"},                 # bad first character
        {"content_hash": "not-a-hash"},
        {"content_hash": "ABCDEF" * 10},               # wrong alphabet/length
        {"destination": "openai.com"},                 # free-text destination
        {"destination": "wherever the clinician typed"},
    ],
)
def test_writer_rejects_free_text(store, kwargs):
    base = {
        "case_id": "case-a",
        "action": "case.create",
        "object_type": "case",
        "object_id": "case-a",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        append_audit(store, **base)
    # Nothing was written.
    assert store._connect().execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_writer_accepts_allowlisted_values(store):
    append_audit(
        store,
        case_id="case-a",
        action="egress.send",
        object_type="egress_request",
        object_id="req-1",
        content_hash="a" * 64,
        destination="fake",
    )
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 1, None)


def test_writer_accepts_token_urlsafe_leading_dash_and_underscore(store):
    """egress request ids come from secrets.token_urlsafe(18): ~3% of them
    start with ``-`` or ``_`` and the audit writer must accept them."""
    for request_id in ("-abc123", "_abc123"):
        append_audit(
            store,
            case_id="case-a",
            action="egress.prepare",
            object_type="egress_request",
            object_id=request_id,
        )
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 2, None)


def test_egress_prepare_with_leading_dash_request_id(tmp_path, monkeypatch):
    """A real prepare whose token_urlsafe(18) is forced to ``-`` must not 500."""
    import importlib

    from fastapi.testclient import TestClient

    egress_module = importlib.import_module("psychtool.core.egress")
    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(
        app_module, "default_db_path", lambda: tmp_path / "psychtool.db"
    )
    monkeypatch.setattr(
        egress_module.secrets, "token_urlsafe", lambda n: "-abc123"
    )
    app = app_module.create_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Psychtool-Token": app.state.session_token}
    assert client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers).status_code == 201
    client.put(
        "/api/workspaces/case-a/sections/history",
        json={"template_id": "intake-report", "template_version": 1, "text": "draft"},
        headers=headers,
    )

    response = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": "history",
            "claim_ids": [],
            "instructions": "Write the section.",
            "purpose": "section_generation",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["request_id"] == "-abc123"


# -- (iv) tamper detection with the trigger dropped in a raw connection ---------


def test_tamper_detected_after_dropping_trigger(tmp_path):
    db = tmp_path / "psychtool.db"
    store = SqliteStore(db)
    store.create_case("case-a")
    store.create_case("case-b")
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 2, None)

    raw = sqlite3.connect(db)  # separate raw connection, not the store's
    raw.execute("DROP TRIGGER audit_log_no_update")
    raw.execute("UPDATE audit_log SET object_id = 'forged' WHERE seq = 1")
    raw.commit()
    raw.close()

    ok, count, bad = verify_audit_chain(store)
    assert ok is False
    assert bad == 1


def test_deleted_row_detected(tmp_path):
    db = tmp_path / "psychtool.db"
    store = SqliteStore(db)
    store.create_case("case-a")
    store.create_case("case-b")
    store.create_case("case-c")
    raw = sqlite3.connect(db)
    raw.execute("DROP TRIGGER audit_log_no_delete")
    raw.execute("DELETE FROM audit_log WHERE seq = 2")
    raw.commit()
    raw.close()
    ok, _, bad = verify_audit_chain(store)
    assert ok is False


# -- (v) restart durability and v1->v2 migration --------------------------------


def test_chain_survives_restart(tmp_path):
    db = tmp_path / "psychtool.db"
    store = SqliteStore(db)
    store.create_case("case-a")
    case = store.case("case-a")
    case.import_material(
        material_id="doc-1",
        title="t",
        provider="p",
        date="2026-11-24",
        passages=[],
    )
    first = [dict(row) for row in store.list_audit_entries()]

    reopened = SqliteStore(db)  # fresh store over the same file
    ok, count, bad = verify_audit_chain(reopened)
    assert (ok, count, bad) == (True, 2, None)
    assert [dict(row) for row in reopened.list_audit_entries()] == first

    # New rows chain onto the pre-restart tail.
    reopened.create_case("case-b")
    ok, count, bad = verify_audit_chain(reopened)
    assert (ok, count, bad) == (True, 3, None)
    entries = [dict(row) for row in reopened.list_audit_entries()]
    assert entries[2]["prev_hash"] == entries[1]["entry_hash"]


def _build_v1_database(db) -> None:
    """A minimal genuine v1 database (pre-audit schema, user_version=1).

    Table shapes match PT-02 (git HEAD): egress_requests still has the
    four-status CHECK without ``send_interrupted``.
    """
    raw = sqlite3.connect(db)
    raw.executescript(
        """
        CREATE TABLE cases (
            case_id     TEXT PRIMARY KEY CHECK (length(case_id) BETWEEN 1 AND 64),
            data_tier   TEXT NOT NULL CHECK (data_tier IN ('synthetic', 'real')),
            created_at  TEXT NOT NULL
        );
        CREATE TABLE known_names (
            case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
            name    TEXT NOT NULL,
            PRIMARY KEY (case_id, name)
        );
        CREATE TABLE materials (
            case_id    TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
            material_id TEXT NOT NULL,
            version    INTEGER NOT NULL CHECK (version >= 1),
            title      TEXT NOT NULL,
            provider   TEXT NOT NULL,
            date       TEXT NOT NULL,
            PRIMARY KEY (case_id, material_id, version)
        );
        CREATE TABLE passages (
            case_id     TEXT NOT NULL,
            material_id TEXT NOT NULL,
            version     INTEGER NOT NULL,
            passage_id  TEXT NOT NULL,
            position    INTEGER NOT NULL CHECK (position >= 1),
            text        TEXT NOT NULL,
            PRIMARY KEY (case_id, material_id, version, passage_id)
        );
        CREATE TABLE egress_requests (
            case_id               TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
            request_id            TEXT NOT NULL,
            purpose               TEXT NOT NULL,
            data_tier             TEXT NOT NULL,
            provider_base_url     TEXT NOT NULL,
            envelope              TEXT NOT NULL,
            source_refs           TEXT NOT NULL,
            identifier_categories TEXT NOT NULL,
            content_hash          TEXT NOT NULL,
            status                TEXT NOT NULL
                CHECK (status IN ('prepared', 'approved', 'sent', 'invalidated')),
            approval_mode         TEXT CHECK (approval_mode IN ('human', 'synthetic_auto')),
            reviewer              TEXT,
            approval_reason       TEXT,
            prepared_at           TEXT NOT NULL,
            approved_at           TEXT,
            sent_at               TEXT,
            send_lock_owner       TEXT,
            transition_lock_owner TEXT,
            PRIMARY KEY (case_id, request_id)
        );
        """
    )
    raw.execute("PRAGMA user_version = 1")
    raw.execute("INSERT INTO cases VALUES ('case-old', 'synthetic', '2026-01-01')")
    raw.commit()
    raw.close()


def test_v1_database_migrates_to_v2(tmp_path):
    db = tmp_path / "psychtool.db"
    _build_v1_database(db)

    store = SqliteStore(db)
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    # Old data intact.
    row = connection.execute(
        "SELECT data_tier FROM cases WHERE case_id = 'case-old'"
    ).fetchone()
    assert row["data_tier"] == "synthetic"
    # Audit table and triggers exist and the chain starts from genesis.
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'audit_log'"
    ).fetchone()[0] == 1
    triggers = {
        r[0]
        for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    assert {"audit_log_no_update", "audit_log_no_delete"} <= triggers
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 0, None)
    store.create_case("case-new")
    entries = [dict(r) for r in store.list_audit_entries()]
    assert entries[0]["prev_hash"] == GENESIS_PREV_HASH
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 1, None)


def test_v1_migration_rebuilds_egress_requests_and_recovery_works(tmp_path):
    """A v1 row whose CHECK forbids ``send_interrupted`` must survive the
    table rebuild, and recovery must then be able to set that status."""
    from psychtool.store.recovery import BOOT_ID, recover_stale_send_locks

    db = tmp_path / "psychtool.db"
    _build_v1_database(db)
    raw = sqlite3.connect(db)
    raw.execute(
        "INSERT INTO egress_requests VALUES ("
        " 'case-old', 'req-locked', 'section_generation', 'synthetic',"
        " 'https://provider.invalid/v1', '{}', '[]', '[]',"
        " '" + "a" * 64 + "', 'approved', 'synthetic_auto', NULL,"
        " 'reason', '2026-01-01', '2026-01-01', NULL,"
        " 'FOREIGNBOOT:1:deadbeef', NULL)"
    )
    raw.commit()
    raw.close()

    store = SqliteStore(db)
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    # Row copied with all fields intact.
    row = connection.execute(
        "SELECT status, send_lock_owner FROM egress_requests"
        " WHERE request_id = 'req-locked'"
    ).fetchone()
    assert row["status"] == "approved"
    assert row["send_lock_owner"] == "FOREIGNBOOT:1:deadbeef"
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    # Recovery can now write the v2-only status.
    recovered = recover_stale_send_locks(store, BOOT_ID)
    assert len(recovered) == 1
    row = connection.execute(
        "SELECT status, send_lock_owner FROM egress_requests"
        " WHERE request_id = 'req-locked'"
    ).fetchone()
    assert row["status"] == "send_interrupted"
    assert row["send_lock_owner"] is None
    audit = [
        dict(r)
        for r in connection.execute(
            "SELECT * FROM audit_log WHERE action = 'egress.send_lock_recovered'"
        ).fetchall()
    ]
    assert len(audit) == 1
    assert audit[0]["object_id"] == "req-locked"
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v2_database_migrates_to_v3_with_confirmation_column(tmp_path):
    """A PT-03 v2 database opens, gains ``cases.synthetic_confirmed_at``,
    keeps every existing row and its audit chain, and an existing case starts
    unconfirmed (NULL) so the R2-AC3 gate applies to pre-upgrade cases too."""
    db = tmp_path / "psychtool.db"
    # Build a genuine v2 database: run the v1 fixture, then apply only the
    # v2 migration statements and set user_version=2.
    from psychtool.store.sqlite_store import _MIGRATION_STATEMENTS

    _build_v1_database(db)
    raw = sqlite3.connect(db)
    raw.row_factory = sqlite3.Row
    for statement in _MIGRATION_STATEMENTS[2]:
        raw.execute(statement)
    raw.execute("PRAGMA user_version = 2")
    append_audit(
        raw,
        case_id="case-old",
        action="case.create",
        object_type="case",
        object_id="case-old",
    )
    raw.commit()
    raw.close()

    store = SqliteStore(db)
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(cases)").fetchall()
    }
    assert "synthetic_confirmed_at" in columns
    # Existing row intact, confirmation starts unset.
    row = connection.execute(
        "SELECT data_tier, synthetic_confirmed_at FROM cases"
        " WHERE case_id = 'case-old'"
    ).fetchone()
    assert row["data_tier"] == "synthetic"
    assert row["synthetic_confirmed_at"] is None
    case = store.case("case-old")
    assert case.is_synthetic_confirmed() is False
    assert case.confirm_synthetic() is True
    assert case.is_synthetic_confirmed() is True
    # The audit chain is intact across the migration: the one v2 row plus
    # the confirmation row the store appends in the same transaction.
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 2, None)
    last = connection.execute(
        "SELECT action, object_type, object_id FROM audit_log ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert tuple(last) == ("case.confirm_synthetic", "case", "case-old")
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# -- error-response scan ---------------------------------------------------------


def test_error_bodies_do_not_echo_marker(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    app_module = importlib.import_module("psychtool.server.app")
    monkeypatch.setattr(app_module, "default_db_path", lambda: tmp_path / "psychtool.db")
    app = app_module.create_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Psychtool-Token": app.state.session_token}

    client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers)
    responses = [
        # Unknown case -> 404 with a fixed message.
        client.get("/api/workspaces/no-such-case/materials", headers=headers),
        # Duplicate case -> 409.
        client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers),
        # Unknown egress request.
        client.get("/api/workspaces/case-a/egress/nope", headers=headers),
        # Section save with marker free text and a bad field.
        client.put(
            "/api/workspaces/case-a/sections/history",
            json={
                "template_id": "no-such-template",
                "template_version": 1,
                "text": MARKER,
            },
            headers=headers,
        ),
    ]
    for response in responses:
        assert response.status_code >= 400
        assert MARKER not in response.text


# -- atomicity: the audit row commits with the state change it describes --------


def _audit_actions(db) -> list[str]:
    rows = SqliteStore(db)._connect().execute(
        "SELECT action FROM audit_log ORDER BY seq"
    ).fetchall()
    return [row["action"] for row in rows]


def _paste_and_suggest(client, headers) -> dict:
    """Paste a synthetic material and return one real claim suggestion."""
    assert client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "doc-1",
            "title": "synthetic",
            "provider": "synthetic",
            "date": "synthetic date",
            "text": "Synthetic observation for the claim.",
            "synthetic_confirmed": True,
        },
        headers=headers,
    ).status_code == 200
    suggestions = client.get(
        "/api/workspaces/case-a/materials/doc-1/suggestions?provider_role=self_report",
        headers=headers,
    )
    assert suggestions.status_code == 200, suggestions.text
    return suggestions.json()[0]


def test_claim_accept_and_audit_row_roll_back_together(tmp_path, monkeypatch):
    """An audit failure during claim insert must roll the claim back too."""
    import importlib

    from fastapi.testclient import TestClient
    from psychtool.store import sqlite_store as store_module

    app_module = importlib.import_module("psychtool.server.app")
    db = tmp_path / "psychtool.db"
    monkeypatch.setattr(app_module, "default_db_path", lambda: db)
    app = app_module.create_app()
    # Surface the injected persistence failure as a 500 response; the
    # transaction has already rolled back by the time it reaches the route.
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    headers = {"X-Psychtool-Token": app.state.session_token}

    assert client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers).status_code == 201
    suggestion = _paste_and_suggest(client, headers)

    def broken_append_audit(self, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(
        store_module.CaseStore, "append_audit", broken_append_audit
    )
    response = client.post(
        "/api/workspaces/case-a/claims", json=suggestion, headers=headers
    )
    assert response.status_code >= 400

    # Neither the claim nor an audit row survived the failed transaction.
    monkeypatch.undo()
    store = SqliteStore(db)
    assert store.case("case-a").list_claims() == []
    assert "claim.accept" not in _audit_actions(db)


def test_sent_save_and_audit_row_roll_back_together_fail_closed(tmp_path, monkeypatch):
    """If the ``sent`` audit write fails, the status must NOT become ``sent``
    without an audit row. The transport already ran, so the send lock stays
    held (fail-closed) exactly like the post-transport persistence-failure
    path, and a new boot recovers the request to ``send_interrupted``."""
    import importlib

    from fastapi.testclient import TestClient
    from psychtool.store import sqlite_store as store_module
    from psychtool.store.recovery import recover_stale_send_locks

    app_module = importlib.import_module("psychtool.server.app")
    db = tmp_path / "psychtool.db"
    monkeypatch.setattr(app_module, "default_db_path", lambda: db)
    app = app_module.create_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Psychtool-Token": app.state.session_token}

    assert client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers).status_code == 201
    assert client.put(
        "/api/workspaces/case-a/sections/history",
        json={"template_id": "intake-report", "template_version": 1, "text": "draft"},
        headers=headers,
    ).status_code == 200
    prepared = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": "history",
            "claim_ids": [],
            "instructions": "Write the section.",
            "purpose": "section_generation",
        },
        headers=headers,
    )
    assert prepared.status_code == 200, prepared.text
    request_id = prepared.json()["request_id"]
    approved = client.post(
        f"/api/workspaces/case-a/egress/{request_id}/approve",
        json={
            "synthetic_auto_reason": "synthetic fixture",
            "content_hash": prepared.json()["content_hash"],
        },
        headers=headers,
    )
    assert approved.status_code == 200, approved.text

    original_append_audit = store_module.CaseStore.append_audit

    def broken_append_audit(self, **kwargs):
        if kwargs.get("action") == "egress.send":
            raise RuntimeError("injected audit failure")
        return original_append_audit(self, **kwargs)

    monkeypatch.setattr(
        store_module.CaseStore, "append_audit", broken_append_audit
    )
    response = client.post(
        f"/api/workspaces/case-a/egress/{request_id}/send", headers=headers
    )
    # The send route surfaces the failed persistence, never a silent success.
    assert response.status_code >= 400

    # (b1) The request must NOT be ``sent`` with no audit row: the whole
    # ``sent`` transaction rolled back, so the status is still ``approved``.
    row = SqliteStore(db)._connect().execute(
        "SELECT status, send_lock_owner FROM egress_requests"
        " WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    assert row["status"] == "approved"
    assert "egress.send" not in _audit_actions(db)
    # (b2) The transport ran, so the send lock must remain held (fail-closed).
    assert row["send_lock_owner"] is not None

    # (b3) A new boot recovers the stale lock to ``send_interrupted`` with a
    # recovery audit row in the same transaction. The lock was written by
    # *this* process, so the "new boot" is simulated with a fresh boot id.
    monkeypatch.undo()
    restarted = SqliteStore(db)
    recovered = recover_stale_send_locks(restarted, "new-boot-id")
    assert len(recovered) == 1
    assert recovered[0]["request_id"] == request_id
    assert recovered[0]["prior_status"] == "approved"
    final = restarted.case("case-a").get_egress_request(request_id)
    assert final.status == "send_interrupted"
    actions = _audit_actions(db)
    assert actions.count("egress.send_lock_recovered") == 1
    assert "egress.send" not in actions


def test_full_flow_produces_one_audit_row_per_event_in_order(tmp_path, monkeypatch):
    """case.create, material.import, case.confirm_synthetic (from the paste
    body), claim.accept, egress.prepare, egress.approve, egress.send —
    exactly once each, in order."""
    import importlib

    from fastapi.testclient import TestClient

    app_module = importlib.import_module("psychtool.server.app")
    db = tmp_path / "psychtool.db"
    monkeypatch.setattr(app_module, "default_db_path", lambda: db)
    app = app_module.create_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Psychtool-Token": app.state.session_token}

    assert client.post("/api/workspaces", json={"case_id": "case-a"}, headers=headers).status_code == 201
    suggestion = _paste_and_suggest(client, headers)
    assert client.post(
        "/api/workspaces/case-a/claims", json=suggestion, headers=headers
    ).status_code == 200
    prepared = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": "history",
            "claim_ids": [suggestion["id"]],
            "instructions": "Write the section.",
            "purpose": "section_generation",
        },
        headers=headers,
    )
    assert prepared.status_code == 200, prepared.text
    request_id = prepared.json()["request_id"]
    assert client.post(
        f"/api/workspaces/case-a/egress/{request_id}/approve",
        json={
            "synthetic_auto_reason": "synthetic fixture",
            "content_hash": prepared.json()["content_hash"],
        },
        headers=headers,
    ).status_code == 200
    sent = client.post(f"/api/workspaces/case-a/egress/{request_id}/send", headers=headers)
    assert sent.status_code == 200, sent.text

    assert _audit_actions(db) == [
        "case.create",
        "material.import",
        "case.confirm_synthetic",
        "claim.accept",
        "egress.prepare",
        "egress.approve",
        "egress.send",
    ]
    send_row = SqliteStore(db)._connect().execute(
        "SELECT destination, content_hash FROM audit_log WHERE action = 'egress.send'"
    ).fetchone()
    assert send_row["destination"] == "fake"
    assert send_row["content_hash"] == prepared.json()["content_hash"]


def test_invalidation_writes_audit_row_in_same_transaction(tmp_path):
    """A status change to ``invalidated`` appends ``egress.invalidate`` in the
    same transaction as the state change."""
    from psychtool.config import Config
    from psychtool.core.egress import invalidate_request, prepare_egress_request

    db = tmp_path / "psychtool.db"
    store = SqliteStore(db)
    store.create_case("case-a")
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
    invalidate_request(case, request.request_id)

    actions = _audit_actions(db)
    assert actions == ["case.create", "egress.prepare", "egress.invalidate"]
    row = store._connect().execute(
        "SELECT content_hash FROM audit_log WHERE action = 'egress.invalidate'"
    ).fetchone()
    assert row["content_hash"] == request.content_hash
