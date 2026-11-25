"""Per-section report state: versioning, review gates, claim validation."""

import pytest

import psychtool.core.sections as sections_module
from psychtool.core.workspace import init_workspace
from psychtool.core.claims import add_claim
from psychtool.core.report_templates import (
    is_clinician_authored_section,
    load_template,
)
from psychtool.core.sections import (
    ClinicianAuthoredSectionError,
    build_section_request_input,
    get_section,
    save_section,
    section_states,
)


_ENV_VARS = (
    "PSYCHTOOL_BASE_URL",
    "PSYCHTOOL_MODEL",
    "PSYCHTOOL_JUDGE_MODEL",
    "PSYCHTOOL_DATA_TIER",
    "PSYCHTOOL_API_KEY",
    "PSYCHTOOL_REDACT",
)


@pytest.fixture(autouse=True)
def _clear_psychtool_environment(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def ws(tmp_path):
    return init_workspace(tmp_path / "case-a", case_id="case-a")


def _add_claim(ws, cid, text="statement"):
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


def _save(ws, section_id, text, claim_ids, status="draft", reviewer=None):
    return save_section(
        ws,
        template_id="intake-report",
        template_version=1,
        section_id=section_id,
        text=text,
        claim_ids=claim_ids,
        status=status,
        reviewer=reviewer,
    )


def test_save_and_get_roundtrip(ws):
    _add_claim(ws, "c1")
    _save(ws, "history", "draft text", ["c1"])
    draft = get_section(ws, "intake-report", "history")
    assert draft is not None
    assert draft.version == 1
    assert draft.case_id == "case-a"
    assert draft.text == "draft text"
    assert draft.claim_ids == ["c1"]
    assert draft.status == "draft"


def test_section_states_defaults_to_empty_in_template_order(ws):
    states = section_states(ws, "intake-report")
    assert [s["section_id"] for s in states][:3] == [
        "header",
        "client_details",
        "reason_for_referral",
    ]
    assert all(s["status"] == "empty" for s in states)
    assert states[0]["version"] == 0


def test_repeated_save_increments_version(ws):
    _add_claim(ws, "c1")
    _save(ws, "history", "v1", ["c1"])
    _save(ws, "history", "v2", ["c1"])
    assert get_section(ws, "intake-report", "history").version == 2


def test_unknown_claim_rejected(ws):
    with pytest.raises(KeyError, match="claims not in workspace"):
        _save(ws, "history", "text", ["missing"])


def test_unknown_section_rejected(ws):
    with pytest.raises(KeyError, match="not in template"):
        _save(ws, "does_not_exist", "text", [])


def test_wrong_template_version_rejected(ws):
    with pytest.raises(ValueError, match="not 99"):
        save_section(
            ws,
            template_id="intake-report",
            template_version=99,
            section_id="history",
            text="x",
            claim_ids=[],
        )


def test_approve_empty_text_rejected(ws):
    with pytest.raises(ValueError, match="empty text"):
        _save(ws, "history", "   ", [], status="approved")


def test_licensed_clinician_approval_requires_reviewer(ws):
    _add_claim(ws, "c1")
    with pytest.raises(ValueError, match="require a reviewer"):
        _save(ws, "clinical_impressions", "text", ["c1"], status="approved")


def test_licensed_clinician_approval_with_reviewer_succeeds(ws):
    _add_claim(ws, "c1")
    draft = _save(
        ws, "clinical_impressions", "text", ["c1"], status="approved", reviewer="Dr. X"
    )
    assert draft.status == "approved"
    assert draft.reviewer == "Dr. X"
    assert draft.review_gate == "licensed_clinician"


def test_standard_section_approval_without_reviewer_succeeds(ws):
    _add_claim(ws, "c1")
    draft = _save(ws, "history", "text", ["c1"], status="approved")
    assert draft.status == "approved"
    assert draft.review_gate == "standard"


def test_build_section_request_input_builds_complete_prompt_and_claim_refs(ws):
    first = _add_claim(ws, "c1", "first version")
    latest = _add_claim(ws, "c1", "latest version")

    prompt, source_refs = build_section_request_input(
        ws,
        template_id="intake-report",
        template_version=1,
        section_id="history",
        claim_ids=["c1"],
        instructions="Contact evaluator@example.com.",
    )

    assert first.version == 1
    assert latest.version == 2
    assert "latest version" in prompt
    assert "evaluator@example.com" in prompt
    assert [ref.model_dump() for ref in source_refs] == [
        {"kind": "claim", "id": "c1", "version": 2, "evidence_ids": []}
    ]


def test_build_section_request_input_validates_template_and_section(ws):
    with pytest.raises(ValueError, match="not 99"):
        build_section_request_input(
            ws,
            template_id="intake-report",
            template_version=99,
            section_id="history",
            claim_ids=[],
            instructions="x",
        )
    with pytest.raises(KeyError, match="not in template"):
        build_section_request_input(
            ws,
            template_id="intake-report",
            template_version=1,
            section_id="not-a-section",
            claim_ids=[],
            instructions="x",
        )


def test_clinician_authored_helper_matches_content_types_only():
    template = load_template("intake-report")
    sections = {section.id: section for section in template.sections}

    assert is_clinician_authored_section(sections["clinical_impressions"])
    assert is_clinician_authored_section(sections["recommendations"])
    for section_id in ("history", "findings", "summary"):
        assert not is_clinician_authored_section(sections[section_id])


@pytest.mark.parametrize("section_id", ["clinical_impressions", "recommendations"])
def test_build_section_request_input_refuses_clinician_authored_sections(ws, section_id):
    _add_claim(ws, "c1")

    with pytest.raises(ClinicianAuthoredSectionError):
        build_section_request_input(
            ws,
            template_id="intake-report",
            template_version=1,
            section_id=section_id,
            claim_ids=["c1"],
            instructions="Write a diagnosis.",
        )


def test_sections_exposes_no_raw_generation_callback():
    assert not hasattr(sections_module, "generate_section")


def test_build_section_request_input_unknown_claim_rejected(ws):
    with pytest.raises(KeyError):
        build_section_request_input(
            ws,
            template_id="intake-report",
            template_version=1,
            section_id="history",
            claim_ids=["missing"],
            instructions="x",
        )
