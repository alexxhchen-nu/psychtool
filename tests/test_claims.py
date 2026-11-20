"""Candidate claims: provenance, attribution, conflict retention."""

import json

import pytest

from psychtool.core.workspace import init_workspace
from psychtool.core.claims import (
    Claim,
    add_claim,
    list_claims,
    get_claim,
    mark_status,
    claims_by_topic,
)


@pytest.fixture
def ws(tmp_path):
    return init_workspace(tmp_path / "case-a", case_id="case-a")


def _base(**over):
    kw = dict(
        claim_id="c1",
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake interview",
        record_time="2026-10-01",
        category="client_statement",
        topic="sleep",
        text="本人报告入睡困难。",
    )
    kw.update(over)
    return kw


def test_add_claim_stores_full_provenance(ws):
    c = add_claim(ws, **_base())
    assert c.version == 1
    assert c.case_id == "case-a"
    assert c.source_document_id == "doc-1"
    assert c.source_passage_id == "p001"
    assert c.provider_role == "self_report"
    assert c.text == "本人报告入睡困难。"
    assert (ws / "claims" / "c1.v1.json").is_file()


def test_list_and_get_claims(ws):
    add_claim(ws, **_base())
    add_claim(ws, **_base(claim_id="c2", topic="school", text="学校活动记录。"))
    all_claims = list_claims(ws)
    assert {c.id for c in all_claims} == {"c1", "c2"}
    got = get_claim(ws, "c2")
    assert got.id == "c2"
    assert got.version == 1


def test_mark_status_creates_new_version_keeps_old(ws):
    add_claim(ws, **_base())
    updated = mark_status(ws, "c1", "verified")
    assert updated.version == 2
    assert updated.verification_status == "verified"
    assert (ws / "claims" / "c1.v1.json").is_file()
    assert (ws / "claims" / "c1.v2.json").is_file()
    old = json.loads((ws / "claims" / "c1.v1.json").read_text(encoding="utf-8"))
    assert old["verification_status"] == "pending"


def test_attribution_not_flattened(ws):
    self_c = add_claim(ws, **_base(provider_role="self_report"))
    other_c = add_claim(
        ws, **_base(claim_id="c2", provider_role="other_report", text="照护者报告。")
    )
    clin_c = add_claim(
        ws, **_base(claim_id="c3", provider_role="clinician_interpretation", text="临床解释。")
    )
    assert self_c.provider_role == "self_report"
    assert other_c.provider_role == "other_report"
    assert clin_c.provider_role == "clinician_interpretation"
    assert self_c.provider_role != other_c.provider_role != clin_c.provider_role


def test_unknown_event_time_stays_none(ws):
    c = add_claim(ws, **_base(event_time=None))
    assert c.event_time is None
    # not silently filled from record_time
    assert c.record_time == "2026-10-01"
    assert c.event_time is None


def test_conflict_grouped_and_retained(ws):
    add_claim(ws, **_base(claim_id="c1", topic="onset", text="所述事件时间为九月。"))
    add_claim(ws, **_base(claim_id="c2", topic="onset", text="所述事件时间为十月。", provider_role="other_report"))
    group = claims_by_topic(ws, "onset")
    assert {c.id for c in group} == {"c1", "c2"}
    # mark one as conflict-viewed; originals (text) must be retained
    mark_status(ws, "c1", "conflict-viewed")
    c1 = get_claim(ws, "c1")
    assert c1.verification_status == "conflict-viewed"
    assert c1.text == "所述事件时间为九月。"
    assert len(claims_by_topic(ws, "onset")) == 2


def test_provider_role_must_be_known(ws):
    with pytest.raises(ValueError):
        add_claim(ws, **_base(provider_role="mystery_role"))
