"""PT-08 (GROK-38) store-level dimension tests (ADR 0016).

Against a real CaseStore with synthetic data only: the one-list rule and
its 409, case isolation, prototype name parsing into the dimensions table
(with verbatim spans verified through the spans helpers), the rule-4
held-back count, dims materials never feeding evidence extraction, and
her dimension choice surviving refresh and a new list version (stable
dim_ ids), including the stale-choice needs_review state.
"""

from __future__ import annotations

import pytest

from psychtool.core.dimensions import NOT_DIAGNOSIS, STALE_CHOICE_REASON
from psychtool.core.extract import RuleExtractor
from psychtool.core.spans import Span, span_text, verify_quote
from psychtool.core.workspace import Material, Passage
from psychtool.store.audit import verify_audit_chain
from psychtool.store.sqlite_store import (
    DimensionListExistsError,
    SqliteStore,
)


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


@pytest.fixture
def case(store):
    store.create_case("case-dims")
    return store.case("case-dims")


PROTOTYPE_LIST_TEXT = (
    "This is a clinician-made working list of the working areas we track "
    "for this practice, not any official criteria or diagnostic text.\n"
    "Dimension 1: Attention\n"
    "Dimension 2: Reading and decoding\n"
    "Dimension 3: Sleep and routine\n"
    "Dimension 4: Social interaction\n"
    "Dimension 5: Mood and emotion\n"
    "Dimension 6: Memory and processing speed"
)

NOTE_TEXT = (
    "He is distractible and cannot focus during homework.\n"
    "He reads slowly and mixes up words.\n"
    "He rides his bike after school."
)


def _upload_list(case: "object", text: str = PROTOTYPE_LIST_TEXT,
                 material_id: str = "dims-list", title: str = "Working list") -> Material:
    return case.import_material(
        material_id=material_id,
        title=title,
        provider="synthetic author",
        date="2026-11-24",
        kind="dims",
        passages=[Passage(id="p1", text=text)],
    )


def _upload_note(case: "object") -> Material:
    return case.import_material(
        material_id="note",
        title="Caregiver note",
        provider="synthetic author",
        date="2026-11-24",
        passages=[Passage(id=f"p{i}", text=t) for i, t in enumerate(NOTE_TEXT.split("\n\n"), 1)],
    )


# -- the one-list rule ---------------------------------------------------------


def test_second_dims_material_id_raises(store, case):
    _upload_list(case)
    with pytest.raises(DimensionListExistsError, match="dimension list exists"):
        _upload_list(case, text="Dimension 1: Sleep", material_id="other-list")


def test_reupload_same_material_id_creates_new_version_and_rebuilds(case):
    _upload_list(case)
    first = case.list_dimensions()
    assert first["has_list"] and first["list"]["version"] == 1
    assert len(first["dimensions"]) == 6
    second_material = _upload_list(
        case,
        text=PROTOTYPE_LIST_TEXT + "\nDimension 7: Processing speed",
    )
    assert second_material.version == 2
    case.build_dimensions()
    second = case.list_dimensions()
    assert second["list"]["version"] == 2
    assert len(second["dimensions"]) == 7


def test_case_isolation_for_dimensions(store):
    store.create_case("case-a")
    store.create_case("case-b")
    _upload_list(store.case("case-a"))
    case_b = store.case("case-b")
    assert case_b.list_dimensions()["has_list"] is False
    assert case_b.list_dimensions()["dimensions"] == []
    _upload_list(case_b, text="Dimension 1: Only here", title="B list")
    names_a = [d["name"] for d in store.case("case-a").list_dimensions()["dimensions"]]
    names_b = [d["name"] for d in case_b.list_dimensions()["dimensions"]]
    assert names_a == [
        "Attention",
        "Reading and decoding",
        "Sleep and routine",
        "Social interaction",
        "Mood and emotion",
        "Memory and processing speed",
    ]
    assert names_b == ["Only here"]


# -- list parsing into the dimensions table ------------------------------------


def test_prototype_intro_line_is_not_a_dimension(case):
    _upload_list(case)
    result = case.build_dimensions()
    assert result["dimensions"] == 6
    assert result["held_back"] == 1  # exactly the intro sentence
    names = [d["name"] for d in case.list_dimensions()["dimensions"]]
    assert "This is a clinician-made working list" not in " ".join(names)


def test_stored_names_are_verbatim_substrings_with_verified_spans(case):
    _upload_list(case)
    case.build_dimensions()
    material = case.get_material("dims-list")
    for dim in case.list_dimensions()["dimensions"]:
        span = Span(
            material_id="dims-list",
            material_version=material.version,
            passage_id=dim["passage_id"],
            start=dim["start"],
            end=dim["end"],
        )
        assert verify_quote(material, span, dim["name"])
        assert span_text(material, span) == dim["name"]


def test_rule4_line_is_held_back_and_not_a_dimension(case):
    text = (
        "Dimension 1: Attention\n"
        "Dimension 2: Meets criteria for ADHD\n"
        "Dimension 3: Sleep and routine"
    )
    _upload_list(case, text=text)
    result = case.build_dimensions()
    assert result["dimensions"] == 2
    assert result["held_back"] == 1
    names = [d["name"] for d in case.list_dimensions()["dimensions"]]
    assert names == ["Attention", "Sleep and routine"]


def test_line_without_verbatim_name_is_skipped(case):
    # A line whose parsed name never appears verbatim in the passage text
    # cannot be stored. parse_dimension_line only returns names it stripped
    # from the line itself, so simulate by building from a passage where the
    # name is split across a passage boundary: the second passage's label
    # line is fine, but a name repeated with different spacing is not.
    text = "Dimension 1: Attention\nDimension 2: Sleep and routine"
    _upload_list(case, text=text)
    case.build_dimensions()
    names = [d["name"] for d in case.list_dimensions()["dimensions"]]
    assert names == ["Attention", "Sleep and routine"]


def test_held_back_count_visible_in_list_view(case):
    _upload_list(case)
    case.build_dimensions()
    view = case.list_dimensions()
    assert view["held_back"] == 1
    assert view["disclaimer"] == NOT_DIAGNOSIS


# -- dims materials never feed evidence extraction -----------------------------


def test_dims_materials_are_never_evidence_sources(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    summary = case.refresh_evidence(RuleExtractor())
    assert set(summary["materials"]) == {"note"}
    for item in case.list_evidence():
        assert item["material_id"] == "note"


def test_refresh_full_case_skips_dims_material(case):
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    _upload_list(case)  # list lands after evidence exists
    case.build_dimensions()
    summary = case.refresh_evidence(RuleExtractor())  # refresh everything
    assert "dims-list" not in summary["materials"]
    # Suggestions were computed for the note rows against her list.
    distractible = next(
        item for item in case.list_evidence() if "distractible" in item["quote"]
    )
    assert distractible["dimension_name"] == "Attention"
    assert distractible["dim_state"] == "needs_review"
    assert distractible["dim_set_by"] == "suggestion"


# -- her choice survives refresh and new list versions -------------------------


def _dims_by_name(case) -> dict[str, str]:
    return {d["name"]: d["id"] for d in case.list_dimensions()["dimensions"]}


def test_confirm_then_refresh_keeps_her_choice(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = next(i for i in case.list_evidence() if "distractible" in i["quote"])
    case.set_evidence_dimension(item["id"], action="confirm")
    after = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert after["dim_state"] == "confirmed"
    assert after["dim_set_by"] == "clinician"
    assert after["dimension_name"] == "Attention"
    # A full refresh must not overwrite her choice.
    case.refresh_evidence(RuleExtractor())
    reread = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert reread["dim_state"] == "confirmed"
    assert reread["dimension_name"] == "Attention"


def test_change_dimension_survives_a_new_list_version(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = next(i for i in case.list_evidence() if "distractible" in i["quote"])
    target = _dims_by_name(case)["Sleep and routine"]
    case.set_evidence_dimension(item["id"], dimension_id=target)
    after = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert after["dimension_name"] == "Sleep and routine"
    assert after["dim_state"] == "confirmed"
    assert after["dim_set_by"] == "clinician"
    # New list version keeps the same name -> same stable id -> choice stays.
    _upload_list(case, text=PROTOTYPE_LIST_TEXT + "\nDimension 7: Processing speed")
    case.build_dimensions()
    # Re-uploading the list remaps suggestions without touching her choice.
    case.refresh_evidence(RuleExtractor(), material_ids={"dims-list"})
    reread = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert reread["dimension_name"] == "Sleep and routine"
    assert reread["dim_state"] == "confirmed"


def test_none_rejection_survives_refresh(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = next(i for i in case.list_evidence() if "distractible" in i["quote"])
    case.set_evidence_dimension(item["id"], action="none")
    after = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert after["dim_state"] == "rejected"
    assert after["dimension_id"] is None
    case.refresh_evidence(RuleExtractor())
    reread = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert reread["dim_state"] == "rejected"


def test_reset_returns_to_the_suggestion(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = next(i for i in case.list_evidence() if "distractible" in i["quote"])
    case.set_evidence_dimension(item["id"], action="confirm")
    case.set_evidence_dimension(item["id"], action="reset")
    after = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert after["dim_state"] == "needs_review"
    assert after["dim_set_by"] == "suggestion"
    assert after["dimension_name"] == "Attention"


def test_stale_choice_shows_needs_review_and_keeps_the_row(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = next(i for i in case.list_evidence() if "distractible" in i["quote"])
    case.set_evidence_dimension(item["id"], action="confirm")
    # New list version drops Attention entirely.
    _upload_list(
        case,
        text="Dimension 1: Sleep and routine\nDimension 2: Social interaction",
    )
    case.build_dimensions()
    reread = next(i for i in case.list_evidence() if i["id"] == item["id"])
    assert reread["dim_state"] == "needs_review"
    assert reread["dim_reason"] == STALE_CHOICE_REASON
    assert reread["dimension_id"] is None
    assert reread["dim_set_by"] == "clinician"


# -- set_evidence_dimension validation ------------------------------------------


def test_dimension_setter_rejects_unknown_dimension_id(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    with pytest.raises(ValueError, match="allowlist"):
        case.set_evidence_dimension(item["id"], dimension_id="dim_" + "f" * 24)


def test_dimension_setter_rejects_unknown_action_and_combinations(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    with pytest.raises(ValueError):
        case.set_evidence_dimension(item["id"], action="bogus")
    with pytest.raises(ValueError):
        case.set_evidence_dimension(item["id"])
    with pytest.raises(ValueError):
        case.set_evidence_dimension(
            item["id"], action="confirm", dimension_id="dim_" + "a" * 24
        )


def test_confirm_without_a_suggestion_is_rejected(case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = next(i for i in case.list_evidence() if "bike" in i["quote"])
    assert item["dimension_id"] is None
    assert item["dim_state"] == "none"
    with pytest.raises(ValueError, match="no dimension to confirm"):
        case.set_evidence_dimension(item["id"], action="confirm")


def test_dimension_setter_unknown_evidence_raises_keyerror(case):
    with pytest.raises(KeyError):
        case.set_evidence_dimension("ev_missing", action="none")


# -- audit rows for her choices ---------------------------------------------------


def _audit_rows(store, action):
    return [
        dict(row)
        for row in store._connect()
        .execute(
            "SELECT * FROM audit_log WHERE action = ? ORDER BY seq", (action,)
        )
        .fetchall()
    ]


def test_choice_audit_rows_record_allowlisted_values(store, case):
    _upload_list(case)
    case.build_dimensions()
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = next(i for i in case.list_evidence() if "distractible" in i["quote"])
    case.set_evidence_dimension(item["id"], action="confirm")
    case.set_evidence_dimension(item["id"], action="none")
    case.set_evidence_dimension(item["id"], action="reset")
    target = _dims_by_name(case)["Sleep and routine"]
    case.set_evidence_dimension(item["id"], dimension_id=target)

    rows = _audit_rows(store, "evidence.set_dimension")
    assert [r["value"] for r in rows] == ["confirm", "none", "reset", target]
    assert all(r["object_type"] == "evidence" for r in rows)
    # The dimension NAME (her text) is never recorded.
    assert all(r["value"] != "Sleep and routine" for r in rows)

    ok, count, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)


def test_category_role_audit_rows_record_values(store, case):
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    case.set_evidence_choice(item["id"], category="other", set_category=True)
    case.set_evidence_choice(item["id"], role="school", set_role=True)
    case.set_evidence_choice(item["id"], category=None, set_category=True)
    rows_c = _audit_rows(store, "evidence.categorize")
    rows_r = _audit_rows(store, "evidence.set_role")
    assert [r["value"] for r in rows_c] == ["other", "reset"]
    assert [r["value"] for r in rows_r] == ["school"]
    ok, count, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)


# -- audit value allowlist (ADR 0016 / Alex's PT-07 answer 3) -------------------


def test_audit_layer_rejects_free_text_value(store, case):
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    with pytest.raises(ValueError, match="allowlist"):
        case.set_evidence_choice(item["id"], category="her own words", set_category=True)
    # The failed audit append rolls the whole choice back: nothing changed.
    assert case.list_evidence()[0]["category_set_by"] == "suggestion"
    ok, count, bad = verify_audit_chain(store)
    assert (ok, bad) == (True, None)


def test_audit_layer_rejects_dimension_name_as_value(store, case):
    # A dimension NAME is her text; only the dim_ id may be recorded.
    _upload_list(case)
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    with pytest.raises(ValueError, match="allowlist"):
        case.set_evidence_dimension(item["id"], dimension_id="Attention")
    rows = _audit_rows(store, "evidence.set_dimension")
    assert rows == []


def test_audit_layer_rejects_bad_value_for_action(store, case):
    _upload_note(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    from psychtool.store import audit

    with pytest.raises(ValueError, match="allowlist"):
        audit.append_audit(
            store,
            case_id=case.case_id,
            action="evidence.set_dimension",
            object_type="evidence",
            object_id=item["id"],
            value="not-a-dim-id",
        )
    with pytest.raises(ValueError, match="allowlist"):
        audit.append_audit(
            store,
            case_id=case.case_id,
            action="evidence.categorize",
            object_type="evidence",
            object_id=item["id"],
            value="dim_" + "a" * 24,  # a dim id is not a category value
        )


def test_value_column_included_in_entry_hash(store):
    from psychtool.store.audit import GENESIS_PREV_HASH, compute_entry_hash

    base = {
        "case_id": "c",
        "ts": "t",
        "action": "evidence.categorize",
        "object_type": "evidence",
        "object_id": "ev_x",
        "content_hash": None,
        "destination": None,
        "prev_hash": GENESIS_PREV_HASH,
    }
    assert compute_entry_hash(base) == compute_entry_hash(dict(base, value=None))
    assert compute_entry_hash(base) != compute_entry_hash(
        dict(base, value="daily_living")
    )
    assert compute_entry_hash(dict(base, value="other")) != compute_entry_hash(
        dict(base, value="reset")
    )
