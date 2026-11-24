"""R13 (PT-05 / ADR 0013): protected test-content blocking end to end.

- R13-AC1: protected paragraphs are dropped before any store write; the block
  is audited (count + sha256 only) in the same transaction as the import.
- R13-AC2: a checker failure rejects the whole upload; nothing is written.
- The blocked text appears nowhere: not in any table, not in the response,
  not in logs.
- JSON workspace import keeps original passage ids and fails closed on
  claims; egress re-screens material-derived text (defense in depth).
- Schema v3 -> v4 adds audit_log.item_count; old rows keep their hashes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from psychtool.core.workspace import Passage
from psychtool.server.app import create_app
from psychtool.store.audit import verify_audit_chain
from psychtool.store.sqlite_store import SqliteStore
from tests.conftest import build_client

BLOCKED_MARKER = "raw 12 = T 55"
BLOCKED_TEXT = f"Norm table: {BLOCKED_MARKER}."


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "psychtool.db"
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db_path):
    api = build_client(create_app())
    assert api.post("/api/workspaces", json={"case_id": "case-a"}).status_code == 201
    api.post("/api/workspaces/case-a/synthetic-confirmation")
    return api


def _upload(client, filename="notes.md", data=None, material_id="doc-1",
            case_id="case-a"):
    if data is None:
        data = (
            "A normal synthetic paragraph about morning routines.\n\n"
            f"{BLOCKED_TEXT}\n\n"
            "The participant keeps a paper planner.\n"
        ).encode()
    return client.post(
        f"/api/workspaces/{case_id}/materials",
        data={"material_id": material_id, "title": "Synthetic note",
              "provider": "synthetic author", "date": "2026-11-24"},
        files={"file": (filename, data, "application/octet-stream")},
    )


def _table_counts(db_path):
    raw = sqlite3.connect(db_path)
    counts = {
        table: raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("materials", "passages", "audit_log")
    }
    raw.close()
    return counts


# -- R13-AC1: blocked paragraph never stored, audited with count + hash -------


def test_r13_ac1_upload_blocks_norm_table_paragraph(client, db_path, caplog):
    with caplog.at_level(logging.DEBUG):
        response = _upload(client)
    assert response.status_code == 200
    payload = response.json()
    assert payload["blocked_paragraphs"] == 1
    assert "blocked_reason" in payload
    material = payload["material"]
    assert len(material["passages"]) == 2

    # Blocked text is nowhere: response, logs, or any table's stored bytes.
    assert BLOCKED_MARKER not in response.text
    for record in caplog.records:
        assert BLOCKED_MARKER not in record.getMessage()
    raw = sqlite3.connect(db_path)
    for table in ("materials", "passages", "audit_log"):
        rows = raw.execute(f"SELECT * FROM {table}").fetchall()
        for row in rows:
            assert BLOCKED_MARKER not in repr(row)
    blocked_rows = raw.execute(
        "SELECT action, object_type, object_id, content_hash, item_count"
        " FROM audit_log WHERE action = 'material.protected_blocked'"
    ).fetchall()
    assert len(blocked_rows) == 1
    action, object_type, object_id, content_hash, item_count = blocked_rows[0]
    assert (action, object_type, object_id) == (
        "material.protected_blocked", "material", "doc-1")
    assert content_hash == hashlib.sha256(BLOCKED_TEXT.encode()).hexdigest()
    assert item_count == 1
    # And the material row itself was written (partial block, not refusal).
    assert raw.execute(
        "SELECT COUNT(*) FROM materials WHERE material_id = 'doc-1'"
    ).fetchone()[0] == 1
    raw.close()


def test_r13_ac1_block_audit_row_joins_the_import_transaction(client, db_path,
                                                               monkeypatch):
    """If the block audit row cannot be written, no material is stored."""
    from psychtool.store import audit as audit_module

    real_insert = audit_module._insert

    def broken_insert(connection, **kwargs):
        if kwargs.get("action") == "material.protected_blocked":
            raise RuntimeError("injected audit failure")
        return real_insert(connection, **kwargs)

    monkeypatch.setattr(audit_module, "_insert", broken_insert)
    before = _table_counts(db_path)
    failing = build_client(client.app, raise_server_exceptions=False)
    response = _upload(failing)
    # Injected RuntimeError surfaces as the route's fixed 503 ("import
    # unavailable"); the point is that the material write rolled back with it.
    assert response.status_code == 503
    assert _table_counts(db_path) == before


def test_r13_ac1_normal_is_not_blocked(client):
    response = _upload(
        client,
        data=b"Everything was normal.\n\nNormally she sleeps well.\n\n"
             b"Abnormal findings were absent.",
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["blocked_paragraphs"] == 0
    assert "blocked_reason" not in payload
    assert len(payload["material"]["passages"]) == 3


def test_r13_ac1_paste_route_filters_the_same(client, db_path):
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "doc-paste",
            "title": "Synthetic paste",
            "provider": "synthetic author",
            "date": "2026-11-24",
            "text": f"Fine paragraph.\n\n{BLOCKED_TEXT}\n",
            "synthetic_confirmed": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["blocked_paragraphs"] == 1
    assert payload["blocked_reason"]
    assert BLOCKED_MARKER not in response.text
    assert len(payload["material"]["passages"]) == 1
    raw = sqlite3.connect(db_path)
    assert raw.execute(
        "SELECT COUNT(*) FROM passages WHERE text LIKE '%' || ? || '%'",
        (BLOCKED_MARKER,),
    ).fetchone()[0] == 0
    raw.close()


def test_r13_ac1_all_blocked_upload_is_rejected(client, db_path):
    before = _table_counts(db_path)
    response = _upload(client, data=f"{BLOCKED_TEXT}\n\n常模资料见附件。".encode())
    assert response.status_code == 400
    assert response.json()["reason"] == "protected_content"
    assert BLOCKED_MARKER not in response.text
    counts = _table_counts(db_path)
    assert counts["materials"] == before["materials"]
    assert counts["passages"] == before["passages"]
    # One block audit row was written (its own transaction).
    assert counts["audit_log"] == before["audit_log"] + 1


# -- R13-AC2: checker failure rejects the whole upload, nothing written -------


def test_r13_ac2_check_error_rejects_whole_upload(client, db_path, monkeypatch):
    import psychtool.core.ingest as ingest_module

    def broken(texts):
        raise RuntimeError("injected checker failure")

    monkeypatch.setattr(ingest_module, "find_protected", broken)
    before = _table_counts(db_path)
    response = _upload(client)
    assert response.status_code == 503
    assert response.json()["reason"] == "protected_check_failed"
    assert _table_counts(db_path) == before


# -- JSON workspace import ----------------------------------------------------


def _write_workspace(root, *, blocked=False, claim_text="A quote.", cite_blocked=False):
    workspace = root / "ws"
    (workspace / "materials").mkdir(parents=True)
    (workspace / "claims").mkdir(parents=True)
    (workspace / "meta.json").write_text(json.dumps(
        {"case_id": "case-json", "data_tier": "synthetic",
         "created_at": "2026-11-24T00:00:00+00:00"}))
    (workspace / "identifiers.json").write_text(json.dumps({"known_names": []}))
    passages = [{"id": "p001", "text": "An ordinary synthetic passage."}]
    if blocked:
        passages.append({"id": "p002", "text": BLOCKED_TEXT})
    (workspace / "materials" / "m1.v1.json").write_text(json.dumps(
        {"id": "m1", "case_id": "case-json", "version": 1,
         "title": "Synthetic", "provider": "synthetic", "date": "2026-11-24",
         "passages": passages}))
    cite = "p002" if cite_blocked else "p001"
    (workspace / "claims" / "c1.v1.json").write_text(json.dumps(
        {"id": "c1", "case_id": "case-json", "version": 1,
         "source_document_id": "m1", "source_version": 1,
         "source_passage_id": cite,
         "provider_role": "self_report", "observation_setting": "intake",
         "record_time": "2026-11-24", "category": "client_statement",
         "topic": "history", "text": claim_text}))
    return workspace


def test_json_import_drops_blocked_passage_and_keeps_original_ids(tmp_path):
    workspace = _write_workspace(tmp_path, blocked=True)
    store = SqliteStore(tmp_path / "psychtool.db")
    assert store.import_workspace(workspace) == "case-json"
    case = store.case("case-json")
    material = case.get_material("m1")
    assert [p.id for p in material.passages] == ["p001"]
    assert BLOCKED_MARKER not in repr(material)
    rows = store._connect().execute(
        "SELECT item_count, content_hash FROM audit_log"
        " WHERE action = 'material.protected_blocked'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["item_count"] == 1
    assert rows[0]["content_hash"] == hashlib.sha256(BLOCKED_TEXT.encode()).hexdigest()


def test_json_import_rejects_claim_citing_blocked_passage(tmp_path):
    workspace = _write_workspace(tmp_path, blocked=True, cite_blocked=True)
    store = SqliteStore(tmp_path / "psychtool.db")
    with pytest.raises(ValueError, match="protected content in workspace claims"):
        store.import_workspace(workspace)
    assert not store.case_exists("case-json")


def test_json_import_rejects_protected_claim_text(tmp_path):
    workspace = _write_workspace(tmp_path, claim_text=BLOCKED_TEXT)
    store = SqliteStore(tmp_path / "psychtool.db")
    with pytest.raises(ValueError, match="protected content in workspace claims"):
        store.import_workspace(workspace)
    assert not store.case_exists("case-json")


# -- egress defense in depth ---------------------------------------------------


def _seed_protected_case(db_path, *, claim_text=BLOCKED_TEXT):
    """Insert a protected passage+claim directly, simulating pre-PT-05 data."""
    store = SqliteStore(db_path)
    store.create_case("case-a")
    case = store.case("case-a")
    case.import_material(
        material_id="doc-1", title="Synthetic source",
        provider="synthetic", date="synthetic date",
        passages=[Passage(id="p001", text=BLOCKED_TEXT)],
    )
    case.add_claim(
        claim_id="claim-1",
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="synthetic intake",
        record_time="synthetic date",
        category="client_statement",
        topic="history",
        text=claim_text,
    )
    return case


def _egress_counts(db_path):
    raw = sqlite3.connect(db_path)
    count = raw.execute("SELECT COUNT(*) FROM egress_requests").fetchone()[0]
    raw.close()
    return count


@pytest.fixture
def _egress_env(monkeypatch):
    """Local-transport config so prepare passes the pre-existing policy gates
    and the R13 screen is the only thing that can refuse."""
    monkeypatch.setenv("PSYCHTOOL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("PSYCHTOOL_MODEL", "local-model")
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "real")


def _prepare(client):
    return client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={"template_id": "intake-report", "template_version": 1,
              "section_id": "history", "claim_ids": ["claim-1"],
              "instructions": "Write the background section.",
              "purpose": "section_generation"},
    )


def test_egress_prepare_refuses_pre_pt05_protected_material(db_path, _egress_env):
    _seed_protected_case(db_path)
    client = build_client(create_app())
    before = _egress_counts(db_path)
    response = _prepare(client)
    assert response.status_code == 400
    assert response.json()["reason"] == "protected_content"
    assert BLOCKED_MARKER not in response.text
    assert _egress_counts(db_path) == before


def test_egress_prepare_refuses_when_checker_raises(db_path, _egress_env, monkeypatch):
    _seed_protected_case(db_path, claim_text="Clean claim text.")
    import psychtool.core.protected as protected_module

    def broken(text):
        raise RuntimeError("checker down")

    monkeypatch.setattr(protected_module, "is_protected", broken)
    client = build_client(create_app())
    before = _egress_counts(db_path)
    response = _prepare(client)
    assert response.status_code == 400
    assert response.json()["reason"] == "protected_content"
    assert _egress_counts(db_path) == before
