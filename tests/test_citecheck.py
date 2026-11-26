"""PT-12 (GROK-42): sentence-level citecheck, Summary/R7 draft filters, persist-on-save."""

from __future__ import annotations

import sqlite3

import pytest

from psychtool.core.citecheck import (
    DRAFT_FILTER_REASON,
    SUMMARY_DRAFT_REASON,
    DraftFilterBlockedError,
    DraftSentence,
    SentenceEvidence,
    check_draft_text,
    citecheck_text,
    is_summary_section,
    make_sentence_id,
)
from psychtool.core.claims import add_claim
from psychtool.core.report_templates import load_template
from psychtool.core.sections import check_section, get_section, save_section
from psychtool.core.workspace import Passage, init_workspace
from psychtool.store.audit import verify_audit_chain
from psychtool.store.sqlite_store import SqliteStore, _SCHEMA_VERSION
from tests.conftest import build_client
from psychtool.server.app import create_app


QUOTE = "The teacher notes that the client often looks out the window after ten minutes."
UNSOURCED = "The client is one of the most outgoing students in the class."
HISTORY_TEXT = f"{QUOTE} {UNSOURCED}"


def _evidence(evidence_id: str = "ev_aaaaaaaaaaaaaaaaaaaaaaaa", quote: str = QUOTE) -> SentenceEvidence:
    return SentenceEvidence(evidence_id=evidence_id, quote=quote)


def test_is_summary_section_only_for_summary():
    assert is_summary_section("summary") is True
    assert is_summary_section("findings", title="Findings") is False
    assert is_summary_section("history") is False
    assert is_summary_section("other", title="Summary") is True


def test_cited_sentence_is_needs_review_with_evidence_id():
    result = citecheck_text(section_id="history", text=QUOTE, evidence=[_evidence()])
    assert result.blocked is False
    assert len(result.sentences) == 1
    sentence = result.sentences[0]
    assert sentence.evidence_ids == ["ev_aaaaaaaaaaaaaaaaaaaaaaaa"]
    assert sentence.state == "needs_review"
    assert sentence.sentence_id == make_sentence_id("history", 1, QUOTE)
    assert result.text == QUOTE


def test_unsourced_sentence_is_unverified():
    result = citecheck_text(section_id="history", text=UNSOURCED, evidence=[_evidence()])
    assert result.sentences[0].evidence_ids == []
    assert result.sentences[0].state == "unverified"


def test_two_sentence_draft_one_cited_one_not():
    result = citecheck_text(
        section_id="history", text=HISTORY_TEXT, evidence=[_evidence()]
    )
    assert result.text == HISTORY_TEXT
    assert [s.state for s in result.sentences] == ["needs_review", "unverified"]
    assert result.sentences[0].evidence_ids == ["ev_aaaaaaaaaaaaaaaaaaaaaaaa"]
    assert result.sentences[1].evidence_ids == []


def test_my_judgment_is_preserved_without_evidence():
    existing = [
        DraftSentence(
            sentence_id=make_sentence_id("history", 1, UNSOURCED),
            ordinal=1,
            text=UNSOURCED,
            evidence_ids=[],
            state="my_judgment",
        )
    ]
    result = citecheck_text(
        section_id="history",
        text=UNSOURCED,
        evidence=[_evidence()],
        existing_sentences=existing,
    )
    assert result.sentences[0].state == "my_judgment"
    assert result.sentences[0].evidence_ids == []


def test_claimed_verified_unsourced_sentence_is_canonicalized():
    claimed = [
        DraftSentence(
            sentence_id="ignored",
            ordinal=1,
            text=UNSOURCED,
            evidence_ids=[],
            state="verified",
        )
    ]
    result = citecheck_text(
        section_id="history",
        text=UNSOURCED,
        evidence=[_evidence()],
        sentences=claimed,
        strict_evidence=True,
        known_evidence_ids=set(),
    )
    assert result.sentences[0].state == "unverified"


def test_summary_diagnosis_wording_is_blocked():
    text = "The results suggests a diagnosis of a learning difficulty."
    result = citecheck_text(section_id="summary", text=text)
    assert result.blocked is True
    assert result.detail == SUMMARY_DRAFT_REASON
    assert result.text == text
    assert check_draft_text("summary", text) == SUMMARY_DRAFT_REASON


def test_summary_recommendation_wording_is_blocked():
    text = "I recommend weekly sessions with the school counselor."
    result = citecheck_text(section_id="summary", text=text)
    assert result.blocked is True
    assert result.detail == SUMMARY_DRAFT_REASON


def test_disclaimer_phrase_is_not_a_draft_violation():
    text = "The scores are below the mid range. This is not a diagnosis, only a summary of testing."
    assert check_draft_text("history", text) is None
    assert check_draft_text("summary", text) is None


def test_history_diagnosis_wording_is_blocked():
    text = "This presentation is consistent with a diagnosis of inattention."
    result = citecheck_text(section_id="history", text=text)
    assert result.blocked is True
    assert result.detail == DRAFT_FILTER_REASON


def test_criterion_citation_blocked_unless_uploaded():
    text = "The notes mention Criterion A1 in passing."
    assert citecheck_text(section_id="history", text=text).detail == DRAFT_FILTER_REASON
    allowed = citecheck_text(
        section_id="history",
        text=text,
        uploaded_texts=["The teacher's list includes Criterion A1 as a heading."],
    )
    assert allowed.blocked is False


def test_citecheck_does_not_rewrite_multiline_text():
    text = "FAKE OFFLINE RESPONSE — synthetic placeholder only.\n\nSecond paragraph stays intact."
    result = citecheck_text(section_id="history", text=text)
    assert result.text == text
    assert all(s.state == "unverified" for s in result.sentences)


def _file_ws(tmp_path):
    return init_workspace(tmp_path / "case-a", case_id="case-a")


def _add_claim(ws, cid="c1", text="statement"):
    return add_claim(
        ws,
        claim_id=cid,
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-10-01",
        category="client_statement",
        topic="history",
        text=text,
    )


def test_file_workspace_roundtrip_keeps_sentences_and_text(tmp_path):
    ws = _file_ws(tmp_path)
    _add_claim(ws, "c1")
    saved = save_section(
        ws,
        template_id="intake-report",
        template_version=1,
        section_id="history",
        text=HISTORY_TEXT,
        claim_ids=["c1"],
    )
    assert saved.text == HISTORY_TEXT
    assert [s.state for s in saved.sentences] == ["unverified", "unverified"]
    loaded = get_section(ws, "intake-report", "history")
    assert loaded is not None
    assert loaded.text == HISTORY_TEXT
    assert [s.model_dump() for s in loaded.sentences] == [s.model_dump() for s in saved.sentences]


def test_file_workspace_summary_refusal_does_not_write(tmp_path):
    ws = _file_ws(tmp_path)
    _add_claim(ws, "c1")
    with pytest.raises(DraftFilterBlockedError) as exc:
        save_section(
            ws,
            template_id="intake-report",
            template_version=1,
            section_id="summary",
            text="I recommend a change of school.",
            claim_ids=["c1"],
        )
    assert exc.value.reason == SUMMARY_DRAFT_REASON
    assert get_section(ws, "intake-report", "summary") is None


def test_clinical_impressions_may_contain_diagnosis_wording(tmp_path):
    ws = _file_ws(tmp_path)
    _add_claim(ws, "c1")
    text = "My impression is consistent with a diagnosis of a reading difficulty."
    saved = save_section(
        ws,
        template_id="intake-report",
        template_version=1,
        section_id="clinical_impressions",
        text=text,
        claim_ids=["c1"],
        reviewer="Dr. Chen",
    )
    assert saved.text == text
    loaded = get_section(ws, "intake-report", "clinical_impressions")
    assert loaded is not None
    assert loaded.text == text
