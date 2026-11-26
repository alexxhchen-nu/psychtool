"""PT-12 store, API and schema v7→v8 tests for sentence citations."""

from __future__ import annotations

import sqlite3

import pytest

from psychtool.core.citecheck import (
    DRAFT_FILTER_REASON,
    SUMMARY_DRAFT_REASON,
    DraftFilterBlockedError,
    DraftSentence,
    make_sentence_id,
)
from psychtool.core.sections import get_section, save_section
from psychtool.core.extract import RuleExtractor
from psychtool.core.workspace import Passage
from psychtool.server.app import create_app
from psychtool.store.audit import verify_audit_chain
from psychtool.store.sqlite_store import SqliteStore, _SCHEMA_VERSION
from tests.conftest import build_client

QUOTE = "The teacher notes that the client often looks out the window after ten minutes."
UNSOURCED = "The client is one of the most outgoing students in the class."
CLEAN_SUMMARY = f"{QUOTE} {UNSOURCED}"


def _store(tmp_path, monkeypatch, case_id="case-a"):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    store = SqliteStore(tmp_path / "psychtool.db")
    store.create_case(case_id)
    case = store.case(case_id)
    case.import_material(
        material_id="doc-1",
        title="Teacher letter",
        provider="teacher",
        date="2026-10-01",
        passages=[Passage(id="p001", text=QUOTE)],
    )
    case.refresh_evidence(RuleExtractor())
    evidence = case.list_active_evidence()
    assert evidence, "import should have extracted the teacher sentence"
    case.add_claim(
        claim_id="c1",
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="other_report",
        observation_setting="school",
        record_time="2026-10-01",
        category="client_statement",
        topic="history",
        text=QUOTE,
        evidence_ids=[evidence[0]["evidence_id"]],
    )
    return store, case, evidence[0]


def _client(tmp_path, monkeypatch):
    return build_client(create_app())


def test_save_canonicalizes_claimed_verified_unsourced(tmp_path, monkeypatch):
    store, case, _evidence = _store(tmp_path, monkeypatch)
    claimed = DraftSentence(
        sentence_id="sent_deadbeefdeadbeefdeadbeef",
        ordinal=1,
        text=UNSOURCED,
        evidence_ids=[],
        state="verified",
    )
    saved = save_section(
        case,
        template_id="intake-report",
        template_version=1,
        section_id="history",
        text=UNSOURCED,
        claim_ids=["c1"],
        sentences=[claimed],
    )
    assert saved.sentences[0].state == "unverified"
    loaded = get_section(case, "intake-report", "history")
    assert loaded is not None
    assert loaded.sentences[0].state == "unverified"
    assert loaded.text == UNSOURCED


def test_clean_summary_persists_unverified_mark(tmp_path, monkeypatch):
    store, case, evidence = _store(tmp_path, monkeypatch)
    saved = save_section(
        case,
        template_id="intake-report",
        template_version=1,
        section_id="summary",
        text=CLEAN_SUMMARY,
        claim_ids=["c1"],
        reviewer="Dr. Chen",
    )
    assert saved.text == CLEAN_SUMMARY
    assert saved.sentences[0].evidence_ids == [evidence["evidence_id"]]
    assert saved.sentences[0].state == "needs_review"
    assert saved.sentences[1].state == "unverified"
    assert saved.sentences[1].evidence_ids == []
    loaded = get_section(case, "intake-report", "summary")
    assert loaded is not None
    assert loaded.text == CLEAN_SUMMARY
    assert loaded.sentences[1].state == "unverified"
    assert loaded.sentences[0].evidence_ids == [evidence["evidence_id"]]


def test_summary_diagnosis_save_is_refused(tmp_path, monkeypatch):
    store, case, _evidence = _store(tmp_path, monkeypatch)
    with pytest.raises(DraftFilterBlockedError) as exc:
        save_section(
            case,
            template_id="intake-report",
            template_version=1,
            section_id="summary",
            text="The profile suggests a diagnosis of a learning difficulty.",
            claim_ids=["c1"],
        )
    assert exc.value.reason == SUMMARY_DRAFT_REASON
    assert get_section(case, "intake-report", "summary") is None


def test_api_summary_recommendation_is_400(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    response = client.put(
        "/api/workspaces/case-a/sections/summary",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": "I recommend weekly tutoring.",
            "claim_ids": ["c1"],
            "status": "draft",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == SUMMARY_DRAFT_REASON
    states = client.get(
        "/api/workspaces/case-a/sections", params={"template_id": "intake-report"}
    ).json()
    summary = next(s for s in states if s["section_id"] == "summary")
    assert summary["version"] == 0
    assert summary["text"] == ""


def test_api_summary_should_receive_is_400_and_is_not_rewritten(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    text = "The student should receive extra time on written tasks."
    response = client.put(
        "/api/workspaces/case-a/sections/summary",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": text,
            "claim_ids": ["c1"],
            "status": "draft",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == SUMMARY_DRAFT_REASON
    states = client.get(
        "/api/workspaces/case-a/sections", params={"template_id": "intake-report"}
    ).json()
    summary = next(s for s in states if s["section_id"] == "summary")
    assert summary["version"] == 0
    assert summary["text"] == ""


def test_api_summary_false_positive_candidates_are_currently_400(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    text = "The results suggest a slower processing speed on this task."
    response = client.put(
        "/api/workspaces/case-a/sections/summary",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": text,
            "claim_ids": ["c1"],
            "status": "draft",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == SUMMARY_DRAFT_REASON


def test_api_history_diagnosis_is_400(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    response = client.put(
        "/api/workspaces/case-a/sections/history",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": "This is consistent with a diagnosis of inattention.",
            "claim_ids": ["c1"],
            "status": "draft",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == DRAFT_FILTER_REASON


def test_unknown_evidence_id_writes_nothing(tmp_path, monkeypatch):
    store, case, _evidence = _store(tmp_path, monkeypatch)
    bogus = DraftSentence(
        sentence_id=make_sentence_id("history", 1, QUOTE),
        ordinal=1,
        text=QUOTE,
        evidence_ids=["ev_ffffffffffffffffffffffff"],
        state="needs_review",
    )
    with pytest.raises(ValueError, match="unknown evidence id"):
        save_section(
            case,
            template_id="intake-report",
            template_version=1,
            section_id="history",
            text=QUOTE,
            claim_ids=["c1"],
            sentences=[bogus],
        )
    assert get_section(case, "intake-report", "history") is None


def test_cross_case_evidence_id_is_rejected(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, case_id="case-a")
    store_b, case_b, evidence_b = _store(tmp_path, monkeypatch, case_id="case-b")
    # Re-open case-a on the same db.
    case_a = store_b.case("case-a")
    stolen = DraftSentence(
        sentence_id=make_sentence_id("history", 1, QUOTE),
        ordinal=1,
        text=QUOTE,
        evidence_ids=[evidence_b["evidence_id"]],
        state="needs_review",
    )
    with pytest.raises(ValueError, match="unknown evidence id"):
        save_section(
            case_a,
            template_id="intake-report",
            template_version=1,
            section_id="history",
            text=QUOTE,
            claim_ids=["c1"],
            sentences=[stolen],
        )
    assert get_section(case_a, "intake-report", "history") is None


def test_citecheck_endpoint_annotates_and_does_not_write(tmp_path, monkeypatch):
    store, case, evidence = _store(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/workspaces/case-a/sections/history/citecheck",
        json={"text": CLEAN_SUMMARY, "claim_ids": ["c1"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is False
    assert body["detail"] is None
    assert body["sentences"][0]["evidence_ids"] == [evidence["evidence_id"]]
    assert body["sentences"][0]["state"] == "needs_review"
    assert body["sentences"][1]["state"] == "unverified"
    assert get_section(case, "intake-report", "history") is None


def test_citecheck_endpoint_blocked_summary_is_200(tmp_path, monkeypatch):
    store, case, _evidence = _store(tmp_path, monkeypatch)
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/workspaces/case-a/sections/summary/citecheck",
        json={"text": "I recommend a new school placement."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["blocked"] is True
    assert body["detail"] == SUMMARY_DRAFT_REASON
    assert get_section(case, "intake-report", "summary") is None


def test_schema_v7_to_v8_does_not_invent_sentences(tmp_path):
    path = tmp_path / "v7.db"
    raw = sqlite3.connect(str(path))
    raw.execute("PRAGMA foreign_keys=ON")
    raw.executescript(
        """
        CREATE TABLE cases (
            case_id TEXT PRIMARY KEY CHECK (length(case_id) BETWEEN 1 AND 64),
            data_tier TEXT NOT NULL CHECK (data_tier IN ('synthetic', 'real')),
            created_at TEXT NOT NULL,
            synthetic_confirmed_at TEXT
        );
        CREATE TABLE sections (
            case_id          TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
            template_id      TEXT NOT NULL,
            section_id       TEXT NOT NULL,
            version          INTEGER NOT NULL CHECK (version >= 1),
            template_version INTEGER NOT NULL,
            text             TEXT NOT NULL,
            claim_ids        TEXT NOT NULL,
            status           TEXT NOT NULL
                CHECK (status IN ('empty', 'draft', 'needs_review', 'approved')),
            review_gate      TEXT NOT NULL CHECK (review_gate IN ('standard', 'licensed_clinician')),
            reviewer         TEXT,
            updated_at       TEXT NOT NULL,
            PRIMARY KEY (case_id, template_id, section_id, version)
        );
        CREATE TABLE audit_log (
            seq          INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id      TEXT,
            ts           TEXT NOT NULL,
            action       TEXT NOT NULL,
            object_type  TEXT NOT NULL,
            object_id    TEXT NOT NULL,
            content_hash TEXT,
            destination  TEXT,
            prev_hash    TEXT NOT NULL,
            entry_hash   TEXT NOT NULL,
            item_count   INTEGER CHECK (item_count IS NULL OR item_count >= 0),
            value        TEXT
        );
        """
    )
    raw.execute(
        "INSERT INTO cases (case_id, data_tier, created_at) VALUES (?, ?, ?)",
        ("case-a", "synthetic", "2026-11-25T00:00:00+00:00"),
    )
    original = "Teacher-reported history saved before sentence citations existed."
    raw.execute(
        """
        INSERT INTO sections (
            case_id, template_id, section_id, version, template_version,
            text, claim_ids, status, review_gate, reviewer, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "case-a",
            "intake-report",
            "history",
            1,
            1,
            original,
            "[]",
            "draft",
            "standard",
            None,
            "2026-11-25T00:00:00+00:00",
        ),
    )
    raw.execute("PRAGMA user_version=7")
    raw.commit()
    raw.close()

    store = SqliteStore(path)
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    assert _SCHEMA_VERSION == 8
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "section_sentences" in tables
    assert "sentence_evidence" in tables
    assert connection.execute("SELECT COUNT(*) FROM section_sentences").fetchone()[0] == 0
    draft = store.case("case-a").get_section("intake-report", "history")
    assert draft is not None
    assert draft.text == original
    assert draft.sentences == []
    ok, count, first_bad = verify_audit_chain(store)
    assert ok is True
    assert first_bad is None
    assert count == 0
