"""PT-09 chunk 1 (R6 / GROK-39 / ADR 0018): store cascade and atomicity.

When her category choice (``set_evidence_choice``) or dimension choice
(``set_evidence_dimension``) actually changes the EFFECTIVE category key or
effective dimension id, one SQLite transaction must also:

- write a new version of every verified/conflict-viewed claim citing the
  evidence with ``verification_status='pending'`` (text unchanged);
- write a new version of every approved section citing those claims with
  status ``needs_review`` (text, claim_ids and reviewer unchanged);
- invalidate every prepared/approved egress request that references the
  evidence (directly via a source_ref, or via a citing claim); sent requests
  and unrelated requests are never touched.

Role-only writes and no-op writes do not cascade. Both setters return the
evidence row plus an ``invalidation`` summary whose toast string is exact.
A test hook raising mid-cascade must roll EVERYTHING back.

Synthetic data only.
"""

from __future__ import annotations

import pytest

from psychtool.core.egress import EgressRequest, OutboundEnvelope, SourceRef
from psychtool.core.extract import RuleExtractor
from psychtool.core.workspace import Passage
from psychtool.store.audit import verify_audit_chain
from psychtool.store.sqlite_store import SqliteStore

TEACHER_TEXT = "Teacher says he reads slowly in class."
WEATHER_TEXT = "The weather was cloudy that week."
NOTE_TEXT = TEACHER_TEXT + "\n\n" + WEATHER_TEXT

# The exact toast sentences (ADR 0018); assembled here once so every test
# compares against the same contract the UI will display verbatim.
TOAST_START = "Your change was saved."
TOAST_END = "Unsaved text was not changed."
TOAST_NOTHING = "Nothing else needed to be updated."


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


@pytest.fixture
def case(store):
    store.create_case("case-a")
    return store.case("case-a")


def _seed_material(case):
    return case.import_material(
        material_id="m1", title="Note", provider="synthetic", date="2026-11-24",
        passages=[Passage(id="p001", text=NOTE_TEXT)],
    )


def _items(case):
    case.refresh_evidence(RuleExtractor())
    return case.list_evidence()


def _ev(case, needle):
    """The one evidence item whose quote contains ``needle``."""
    return next(item for item in _items(case) if needle in item["quote"])


def _add_claim(case, claim_id, text, evidence_ids, passage="p001"):
    return case.add_claim(
        claim_id=claim_id,
        source_document_id="m1",
        source_version=1,
        source_passage_id=passage,
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-11-24",
        category="client_statement",
        topic="history",
        text=text,
        evidence_ids=list(evidence_ids),
    )


def _egress_request(request_id, refs, status="prepared") -> EgressRequest:
    return EgressRequest(
        request_id=request_id,
        workspace_id="case-a",
        purpose="section_generation",
        data_tier="synthetic",
        provider_base_url="http://127.0.0.1:9/v1",
        envelope=OutboundEnvelope(
            model="m", messages=[{"role": "user", "content": "synthetic"}]
        ),
        source_refs=refs,
        identifier_categories=[],
        content_hash="0" * 64,
        status=status,
        prepared_at="2026-11-25T00:00:00+00:00",
    )


def _save_approved_section(case, section_id, text, claim_ids, reviewer="Dr. Synthetic"):
    return case.save_section(
        template_id="intake-report",
        template_version=1,
        section_id=section_id,
        text=text,
        claim_ids=claim_ids,
        status="approved",
        review_gate="standard",
        reviewer=reviewer,
        updated_at="2026-11-25T00:00:00+00:00",
    )


def _audit_rows(store, action):
    return [
        dict(row)
        for row in store._connect()
        .execute("SELECT * FROM audit_log WHERE action = ? ORDER BY seq", (action,))
        .fetchall()
    ]


def _full_state(store):
    """Every table the cascade can touch, for before/after comparisons."""
    raw = store._connect()
    return {
        table: [tuple(row) for row in raw.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in (
            "evidence",
            "claims",
            "claim_evidence",
            "sections",
            "egress_requests",
            "audit_log",
        )
    }


# -- R6-AC1: category change cascades in one transaction ------------------------


def test_r6_ac1_category_change_invalidates_citing_claim_and_section(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    claim = _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])
    materials_before = [m.id for m in case.list_materials()]

    row = case.set_evidence_choice(ev, category="other", set_category=True)

    # The evidence row shows the new category and carries the summary.
    assert row["category"] == "other"
    assert row["invalidation"]["claims"] == ["c1"]
    assert row["invalidation"]["sections"] == ["history"]
    assert row["invalidation"]["egress"] == []
    # The citing claim is pending again — with identical text and citations.
    after = case.get_claim("c1")
    assert after.verification_status == "pending"
    assert after.text == claim.text
    assert after.evidence_ids == [ev]
    assert after.version == claim.version + 2  # verify + cascade, both versioned
    # The approved section is back to needs_review with the SAME saved text.
    section = case.get_section("intake-report", "history")
    assert section.status == "needs_review"
    assert section.text == "Saved section text."
    assert section.claim_ids == ["c1"]
    assert section.reviewer == "Dr. Synthetic"
    # No new material, no new case.
    assert [m.id for m in case.list_materials()] == materials_before
    assert store.list_cases() == ["case-a"]
    # The evidence change, the claim version and the section version commit
    # together; the audit chain is intact.
    ok, _, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)
    assert [r["value"] for r in _audit_rows(store, "evidence.categorize")] == ["other"]


def test_r6_ac1_conflict_viewed_claims_also_return_to_pending(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "conflict-viewed")
    row = case.set_evidence_choice(ev, category="other", set_category=True)
    assert row["invalidation"]["claims"] == ["c1"]
    assert case.get_claim("c1").verification_status == "pending"


def test_r6_ac1_pending_claims_are_not_versioned_again(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])  # stays pending
    row = case.set_evidence_choice(ev, category="other", set_category=True)
    assert row["invalidation"]["claims"] == []
    assert case.get_claim("c1").version == 1
    assert case.get_claim("c1").verification_status == "pending"


def test_r6_ac1_draft_sections_are_left_alone(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    case.save_section(
        template_id="intake-report", template_version=1, section_id="history",
        text="Draft text.", claim_ids=["c1"], status="draft",
        review_gate="standard", reviewer=None,
        updated_at="2026-11-25T00:00:00+00:00",
    )
    row = case.set_evidence_choice(ev, category="other", set_category=True)
    assert row["invalidation"]["claims"] == ["c1"]
    assert row["invalidation"]["sections"] == []
    section = case.get_section("intake-report", "history")
    assert section.status == "draft"
    assert section.version == 1
    assert section.text == "Draft text."


# -- R7-AC4: dimension change cascades the same way -----------------------------


def _seed_dimensions(case):
    case.import_material(
        material_id="dims-list", title="Working list", provider="synthetic author",
        date="2026-11-24", kind="dims",
        passages=[Passage(
            id="p1",
            text="Dimension 1: Attention\nDimension 2: Sleep and routine",
        )],
    )
    case.build_dimensions()


def _dims_by_name(case):
    return {d["name"]: d["id"] for d in case.list_dimensions()["dimensions"]}


def test_r7_ac4_dimension_change_invalidates_citing_claims(case, store):
    _seed_dimensions(case)
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])
    target = _dims_by_name(case)["Sleep and routine"]

    row = case.set_evidence_dimension(ev, dimension_id=target)

    # The item shows the new dimension; the cascade ran in the same call.
    after = next(i for i in case.list_evidence() if i["id"] == ev)
    assert after["dimension_id"] == target
    assert after["dim_state"] == "confirmed"
    assert row["invalidation"]["claims"] == ["c1"]
    assert row["invalidation"]["sections"] == ["history"]
    assert case.get_claim("c1").verification_status == "pending"
    section = case.get_section("intake-report", "history")
    assert section.status == "needs_review"
    assert section.text == "Saved section text."
    ok, _, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)
    assert [r["value"] for r in _audit_rows(store, "evidence.set_dimension")] == [target]


def test_r7_ac4_change_to_no_dimension_cascades(case, store):
    _seed_dimensions(case)
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    target = _dims_by_name(case)["Sleep and routine"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    # Give the item a dimension first so "none" actually changes the
    # effective dimension id (a no-suggestion item would not cascade).
    case.set_evidence_dimension(ev, dimension_id=target)
    case.mark_claim_status("c1", "verified")
    row = case.set_evidence_dimension(ev, action="none")
    assert row["invalidation"]["claims"] == ["c1"]
    after = next(i for i in case.list_evidence() if i["id"] == ev)
    assert after["dim_state"] == "rejected"


def test_r7_ac4_confirming_the_suggestion_does_not_cascade(case, store):
    """Confirming an already-displayed suggested dimension is a no-op for R6."""
    _seed_dimensions(case)
    # "distractible" matches the "Attention" dimension in HER list, so the
    # item carries a suggestion; confirming it keeps the effective id.
    case.import_material(
        material_id="m1", title="Note", provider="synthetic", date="2026-11-24",
        passages=[Passage(
            id="p001", text="He is distractible and cannot focus during homework."
        )],
    )
    case.refresh_evidence(RuleExtractor())
    item = _ev(case, "distractible")
    ev = item["id"]
    assert item["dimension_id"] is not None  # precondition: a suggestion exists
    _add_claim(case, "c1", item["quote"], [ev])
    case.mark_claim_status("c1", "verified")
    row = case.set_evidence_dimension(ev, action="confirm")
    # The effective id did not change: no cascade, claim stays verified.
    assert row["invalidation"]["claims"] == []
    assert row["invalidation"]["sections"] == []
    assert row["invalidation"]["egress"] == []
    assert case.get_claim("c1").verification_status == "verified"


# -- egress: prepared/approved invalidated, sent and unrelated untouched --------


def test_r6_egress_cascade_only_prepared_and_approved(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    other_ev = _ev(case, "weather")["id"]
    _add_claim(case, "c2", WEATHER_TEXT, [other_ev], passage="p001")

    direct = _egress_request(
        "req-direct",
        [SourceRef(kind="claim", id="c1", version=1, evidence_ids=[ev])],
    )
    via_claim = _egress_request(
        "req-via-claim",
        # The ref's own evidence_ids are empty; it still references the
        # evidence because its claim cites it.
        [SourceRef(kind="claim", id="c1", version=1, evidence_ids=[])],
        status="approved",
    )
    sent = _egress_request(
        "req-sent",
        [SourceRef(kind="claim", id="c1", version=1, evidence_ids=[ev])],
        status="sent",
    )
    unrelated = _egress_request(
        "req-unrelated",
        [SourceRef(kind="claim", id="c2", version=1, evidence_ids=[other_ev])],
    )
    for request in (direct, via_claim, sent, unrelated):
        case.save_egress_request(request)

    row = case.set_evidence_choice(ev, category="other", set_category=True)

    assert row["invalidation"]["egress"] == ["req-direct", "req-via-claim"]
    assert case.get_egress_request("req-direct").status == "invalidated"
    assert case.get_egress_request("req-via-claim").status == "invalidated"
    # sent stays sent; the unrelated request is not touched.
    assert case.get_egress_request("req-sent").status == "sent"
    assert case.get_egress_request("req-unrelated").status == "prepared"
    # Both invalidations were audited (the pre-cascade approvals of the two
    # invalidated requests add their own egress.approve rows).
    assert sorted(
        r["object_id"] for r in _audit_rows(store, "egress.invalidate")
    ) == ["req-direct", "req-via-claim"]
    ok, _, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)


# -- already-pending citing claims still drag sections and egress down ----------


def test_approved_section_citing_already_pending_claim_returns_to_needs_review(
    case, store
):
    """R6-AC1: the section was built on this evidence even if the claim was
    never verified — the approved section must still return to needs_review."""
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])  # stays pending
    _save_approved_section(case, "history", "Saved section text.", ["c1"])

    row = case.set_evidence_choice(ev, category="other", set_category=True)

    # No claim was flipped (none were verified), but the section still goes
    # back to needs_review with its saved text untouched.
    assert row["invalidation"]["claims"] == []
    assert row["invalidation"]["sections"] == ["history"]
    section = case.get_section("intake-report", "history")
    assert section.status == "needs_review"
    assert section.text == "Saved section text."
    assert section.claim_ids == ["c1"]
    assert "section was returned to Needs review" in row["invalidation"]["toast"]
    assert "no longer marked verified" not in row["invalidation"]["toast"]


def test_prepared_egress_with_only_claim_ref_to_pending_claim_is_invalidated(
    case, store
):
    """A kind=claim ref without evidence_ids still references the evidence
    when that claim's latest version cites it — even if it is already pending."""
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])  # stays pending
    case.save_egress_request(
        _egress_request(
            "req-claim-only",
            [SourceRef(kind="claim", id="c1", version=1, evidence_ids=[])],
        )
    )

    row = case.set_evidence_choice(ev, category="other", set_category=True)

    assert row["invalidation"]["claims"] == []
    assert row["invalidation"]["egress"] == ["req-claim-only"]
    assert case.get_egress_request("req-claim-only").status == "invalidated"
    assert [r["object_id"] for r in _audit_rows(store, "egress.invalidate")] == [
        "req-claim-only"
    ]


# -- role-only and no-op writes never cascade ------------------------------------


def test_role_only_change_does_not_cascade(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])

    row = case.set_evidence_choice(ev, role="caregiver", set_role=True)

    assert row["role"] == "caregiver"
    assert row["invalidation"]["claims"] == []
    assert row["invalidation"]["sections"] == []
    assert row["invalidation"]["egress"] == []
    assert case.get_claim("c1").verification_status == "verified"
    assert case.get_section("intake-report", "history").status == "approved"


def test_noop_category_write_does_not_cascade(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    suggested = _ev(case, "reads slowly")["suggested_category"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")

    # Writing the category the item already effectively shows is a no-op.
    row = case.set_evidence_choice(ev, category=suggested, set_category=True)
    assert row["invalidation"]["claims"] == []
    assert case.get_claim("c1").verification_status == "verified"

    # Setting her choice once cascades; setting the SAME choice again does not.
    other = "other" if suggested != "other" else "daily_living"
    first = case.set_evidence_choice(ev, category=other, set_category=True)
    assert first["invalidation"]["claims"] == ["c1"]
    case.mark_claim_status("c1", "verified")
    second = case.set_evidence_choice(ev, category=other, set_category=True)
    assert second["invalidation"]["claims"] == []
    assert case.get_claim("c1").verification_status == "verified"


def test_category_reset_cascades_when_effective_category_changes(case, store):
    """Resetting her stored choice back to a DIFFERENT suggestion cascades."""
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    suggested = _ev(case, "reads slowly")["suggested_category"]
    other = "other" if suggested != "other" else "daily_living"
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])

    # First correction cascades (choice differs from the suggestion).
    first = case.set_evidence_choice(ev, category=other, set_category=True)
    assert first["invalidation"]["claims"] == ["c1"]
    # Restore a clean verified/approved state, still under HER category.
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])

    # Reset to the suggestion: the displayed category changes back -> cascade.
    reset = case.set_evidence_choice(ev, category=None, set_category=True)
    assert reset["category"] is None  # stored choice cleared
    assert reset["invalidation"]["claims"] == ["c1"]
    assert reset["invalidation"]["sections"] == ["history"]
    assert case.get_claim("c1").verification_status == "pending"
    section = case.get_section("intake-report", "history")
    assert section.status == "needs_review"
    assert section.text == "Saved section text."
    assert "no longer marked verified" in reset["invalidation"]["toast"]
    ok, _, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)
    assert [r["value"] for r in _audit_rows(store, "evidence.categorize")] == [
        other,
        "reset",
    ]


def test_category_reset_is_noop_when_choice_matches_suggestion(case, store):
    """Reset with no effective change (no stored choice, or choice ==
    suggestion) must not cascade."""
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    suggested = _ev(case, "reads slowly")["suggested_category"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")

    # No stored choice at all: reset is a pure no-op.
    row = case.set_evidence_choice(ev, category=None, set_category=True)
    assert row["invalidation"]["claims"] == []
    assert case.get_claim("c1").verification_status == "verified"

    # Stored choice equal to the suggestion: reset changes nothing displayed.
    case.set_evidence_choice(ev, category=suggested, set_category=True)
    case.mark_claim_status("c1", "verified")
    row = case.set_evidence_choice(ev, category=None, set_category=True)
    assert row["invalidation"]["claims"] == []
    assert case.get_claim("c1").verification_status == "verified"


def test_noop_dimension_write_does_not_cascade(case, store):
    _seed_dimensions(case)
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    target = _dims_by_name(case)["Sleep and routine"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    case.set_evidence_dimension(ev, dimension_id=target)
    case.mark_claim_status("c1", "verified")
    # Writing the same dimension id again: effective id unchanged, no cascade.
    row = case.set_evidence_dimension(ev, dimension_id=target)
    assert row["invalidation"]["claims"] == []
    assert case.get_claim("c1").verification_status == "verified"


# -- toast: exact strings for several count combinations -------------------------


def _toast(case, ev, **choice):
    return case.set_evidence_choice(ev, **choice)["invalidation"]["toast"]


def test_toast_zero_changes_says_nothing_else_needed(case):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    toast = _toast(case, ev, role="caregiver", set_role=True)
    assert toast == f"{TOAST_START} {TOAST_NOTHING} {TOAST_END}"


def test_toast_singular_counts(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])
    case.save_egress_request(
        _egress_request("req-1", [SourceRef(kind="claim", id="c1", version=1, evidence_ids=[ev])])
    )
    toast = _toast(case, ev, category="other", set_category=True)
    assert toast == (
        f"{TOAST_START} "
        "1 citing statement is no longer marked verified. "
        "1 section was returned to Needs review. "
        "1 prepared request was invalidated and must be prepared again. "
        f"{TOAST_END}"
    )


def test_toast_plural_counts(case, store):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    _add_claim(case, "c2", TEACHER_TEXT + " (second)", [ev])
    case.mark_claim_status("c2", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])
    _save_approved_section(case, "client_details", "Second saved text.", ["c2"])
    for rid in ("req-1", "req-2", "req-3"):
        case.save_egress_request(
            _egress_request(rid, [SourceRef(kind="claim", id="c1", version=1, evidence_ids=[ev])])
        )
    toast = _toast(case, ev, category="other", set_category=True)
    assert toast == (
        f"{TOAST_START} "
        "2 citing statements are no longer marked verified. "
        "2 sections were returned to Needs review. "
        "3 prepared requests were invalidated and must be prepared again. "
        f"{TOAST_END}"
    )


def test_toast_omits_empty_lists(case):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    toast = _toast(case, ev, category="other", set_category=True)
    assert toast == (
        f"{TOAST_START} "
        "1 citing statement is no longer marked verified. "
        f"{TOAST_END}"
    )
    assert "section" not in toast
    assert "request" not in toast


# -- atomicity: a mid-transaction failure rolls back EVERYTHING -------------------


@pytest.mark.parametrize("fail_after", ["claims", "sections", "egress"])
def test_r6_cascade_is_atomic(case, store, fail_after):
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])
    case.save_egress_request(
        _egress_request("req-1", [SourceRef(kind="claim", id="c1", version=1, evidence_ids=[ev])])
    )
    before = _full_state(store)
    audits_before = len(store.list_audit_entries())

    def boom(step: str) -> None:
        if step == fail_after:
            raise RuntimeError("injected failure")

    case.cascade_hook = boom
    with pytest.raises(RuntimeError, match="injected failure"):
        case.set_evidence_choice(ev, category="other", set_category=True)
    case.cascade_hook = None

    # Nothing is half-invalidated: evidence, claims, sections, egress and the
    # audit chain are exactly as they were.
    assert _full_state(store) == before
    assert len(store.list_audit_entries()) == audits_before
    assert case.get_evidence(ev)["category"] is None
    assert case.get_claim("c1").verification_status == "verified"
    assert case.get_section("intake-report", "history").status == "approved"
    assert case.get_egress_request("req-1").status == "prepared"
    ok, _, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)


def test_r6_cascade_atomicity_for_dimension_setter(case, store):
    _seed_dimensions(case)
    _seed_material(case)
    ev = _ev(case, "reads slowly")["id"]
    target = _dims_by_name(case)["Sleep and routine"]
    _add_claim(case, "c1", TEACHER_TEXT, [ev])
    case.mark_claim_status("c1", "verified")
    before = _full_state(store)

    def boom(step: str) -> None:
        if step == "sections":
            raise RuntimeError("injected failure")

    case.cascade_hook = boom
    with pytest.raises(RuntimeError, match="injected failure"):
        case.set_evidence_dimension(ev, dimension_id=target)
    case.cascade_hook = None

    assert _full_state(store) == before
    assert case.get_evidence(ev)["dimension_id"] is None
    assert case.get_claim("c1").verification_status == "verified"
    ok, _, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)


# -- list_egress_requests ----------------------------------------------------------


def test_list_egress_requests_is_case_scoped_and_sorted(store, case):
    case.save_egress_request(_egress_request("req-b", []))
    case.save_egress_request(_egress_request("req-a", []))
    store.create_case("case-b")
    store.case("case-b").save_egress_request(
        _egress_request("req-b", []).model_copy(update={"workspace_id": "case-b"})
    )
    assert [r.request_id for r in case.list_egress_requests()] == ["req-a", "req-b"]
    assert [r.request_id for r in store.case("case-b").list_egress_requests()] == ["req-b"]
