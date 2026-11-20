"""Source invalidation and review summary."""

import json

import pytest

from psychtool.core.workspace import init_workspace, import_material
from psychtool.core.claims import add_claim, mark_status, get_claim
from psychtool.core.draft import freeze_draft_input, persist_generated_draft
from psychtool.core.review import (
    find_stale_claims,
    reopen_stale_claims,
    find_conflicts,
    stale_drafts,
    review_summary,
)


@pytest.fixture
def ws(tmp_path):
    return init_workspace(tmp_path / "case-a", case_id="case-a")


def _add(ws, cid, text, topic="t", doc="doc-1", ver=1, role="self_report"):
    return add_claim(
        ws,
        claim_id=cid,
        source_document_id=doc,
        source_version=ver,
        source_passage_id="p001",
        provider_role=role,
        observation_setting="intake",
        record_time="2026-10-01",
        category="client_statement",
        topic=topic,
        text=text,
    )


def test_stale_when_material_version_bumped(ws):
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text="a\n\nb")
    _add(ws, "c1", "x")
    # material upgraded to v2
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-02", text="a\n\nc")
    stale = find_stale_claims(ws)
    assert [c.id for c in stale] == ["c1"]


def test_claim_citing_latest_version_not_stale(ws):
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text="a")
    _add(ws, "c1", "x", ver=1)
    assert find_stale_claims(ws) == []


def test_reopen_voids_verified_and_keeps_old_locator(ws):
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text="a")
    _add(ws, "c1", "x", ver=1)
    mark_status(ws, "c1", "verified")
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-02", text="b")

    assert reopen_stale_claims(ws) == 1
    c = get_claim(ws, "c1")
    assert c.verification_status == "pending"
    # old locator still points to v1 and remains readable
    assert c.source_version == 1
    assert (ws / "claims" / "c1.v3.json").is_file()


def test_reopen_idempotent_on_pending(ws):
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text="a")
    _add(ws, "c1", "x", ver=1)
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-02", text="b")
    # already pending -> reopen changes nothing
    assert reopen_stale_claims(ws) == 0


def test_conflicts_grouped_by_topic(ws):
    _add(ws, "c1", "时间为九月", topic="onset")
    _add(ws, "c2", "时间为十月", topic="onset")
    _add(ws, "c3", "睡眠一般", topic="sleep")
    conflicts = find_conflicts(ws)
    assert set(conflicts) == {"onset"}
    assert {c.id for c in conflicts["onset"]} == {"c1", "c2"}


def test_stale_drafts_reference_stale_claims(ws):
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text="a")
    _add(ws, "c1", "x", ver=1)
    frozen = freeze_draft_input(ws, claim_ids=["c1"], instructions="x")
    persist_generated_draft(ws, draft_id="d1", frozen_input=frozen, text="y")
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-02", text="b")
    assert stale_drafts(ws) == ["d1"]


def test_review_summary_shape(ws):
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text="a")
    _add(ws, "c1", "时间为九月", topic="onset")
    _add(ws, "c2", "时间为十月", topic="onset")
    s = review_summary(ws)
    assert set(s["conflicts"]) == {"onset"}
    assert set(s["pending"]) == {"c1", "c2"}
    assert s["stale_claims"] == []
    assert s["stale_drafts"] == []
