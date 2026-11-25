"""PT-07 (R5 / ADR 0015): persisted evidence store tests.

Covers the v4->v5 migration with existing data, refresh idempotence and
audit rows, stable ids across rules changes, supersede-never-delete, and the
two required correction tests: her choice survives a rules change, and a
corrected item stays visible after its span disappears from the rules.
"""

from __future__ import annotations

import sqlite3

import pytest

from psychtool.core.categorize import (
    CategoryRule,
    CategorizeRules,
    default_rules,
    suggest_category,
)
from psychtool.core.extract import RuleExtractor
from psychtool.core.workspace import Passage
from psychtool.store.audit import verify_audit_chain
from psychtool.store.sqlite_store import SqliteStore, _SCHEMA_VERSION


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


@pytest.fixture
def case(store):
    store.create_case("case-a")
    return store.case("case-a")


def _seed_material(case, material_id="m1", text=None):
    text = text or (
        "Teacher says he reads slowly in class.\n\n"
        "The weather was cloudy that week."
    )
    passages = [
        Passage(id=f"p{i:03d}", text=block.strip())
        for i, block in enumerate(text.split("\n\n"), start=1)
        if block.strip()
    ]
    return case.import_material(
        material_id=material_id, title="Note", provider="synthetic", date="2026-11-24",
        passages=passages,
    )


def _audit_actions(store, action):
    return [
        dict(row)
        for row in store.list_audit_entries()
        if row["action"] == action
    ]


def _rows(store, case_id="case-a"):
    raw = store._connect()
    return raw.execute(
        "SELECT * FROM evidence WHERE case_id = ? ORDER BY material_id, start",
        (case_id,),
    ).fetchall()


# -- migration v4 -> v5 --------------------------------------------------------


def _build_v4_database(db) -> None:
    """A genuine v4 database: fresh v5 schema minus the evidence table."""
    from psychtool.store.sqlite_store import _SCHEMA_STATEMENTS

    raw = sqlite3.connect(db)
    for statement in _SCHEMA_STATEMENTS:
        if "CREATE TABLE IF NOT EXISTS evidence" in statement:
            continue
        raw.execute(statement)
    raw.execute("PRAGMA user_version = 4")
    raw.commit()
    raw.close()


def test_v4_database_migrates_to_v5_with_existing_data(tmp_path):
    db = tmp_path / "psychtool.db"
    _build_v4_database(db)
    raw = sqlite3.connect(db)
    raw.execute(
        "INSERT INTO cases VALUES ('case-old', 'synthetic', '2026-01-01', NULL)"
    )
    raw.execute(
        "INSERT INTO materials VALUES ('case-old', 'doc', 1, 't', 'p', '2026-01-01')"
    )
    raw.execute(
        "INSERT INTO passages VALUES ('case-old', 'doc', 1, 'p001', 1, 'Old text here.')"
    )
    raw.commit()
    raw.close()

    store = SqliteStore(db)
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    # Existing rows intact; the new table exists and is empty.
    assert connection.execute(
        "SELECT title FROM materials WHERE case_id = 'case-old'"
    ).fetchone()[0] == "t"
    assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    # The audit chain written before the migration still verifies.
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 0, None)
    # And the migrated case can refresh evidence normally.
    case = store.case("case-old")
    summary = case.refresh_evidence(RuleExtractor())
    assert summary["materials"] == {"doc": 1}
    assert len(case.list_evidence()) == 1


# -- refresh -------------------------------------------------------------------


def test_refresh_persists_rows_and_writes_one_audit_row_per_material(case, store):
    _seed_material(case)
    summary = case.refresh_evidence(RuleExtractor())
    assert summary["materials"] == {"m1": 2}
    rows = _rows(store)
    assert len(rows) == 2
    assert all(row["status"] == "active" for row in rows)
    assert all(row["rules_version"] == "rule-1" for row in rows)
    assert all(row["evidence_id"].startswith("ev_") for row in rows)
    audits = _audit_actions(store, "evidence.extract")
    assert len(audits) == 1
    assert audits[0]["object_type"] == "material"
    assert audits[0]["object_id"] == "m1"
    assert audits[0]["item_count"] == 2
    ok, _, _ = verify_audit_chain(store)
    assert ok


def test_refresh_is_idempotent(case, store):
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    audits_before = len(_audit_actions(store, "evidence.extract"))
    rows_before = [dict(row) for row in _rows(store)]
    case.refresh_evidence(RuleExtractor())
    assert len(_audit_actions(store, "evidence.extract")) == audits_before
    assert [dict(row) for row in _rows(store)] == rows_before


def test_refresh_only_uses_latest_material_version(case, store):
    _seed_material(case, text="First version mentions school loudly.\n")
    _seed_material(case, text="Second version mentions homework instead.\n")
    case.refresh_evidence(RuleExtractor())
    rows = _rows(store)
    assert len(rows) == 1
    assert rows[0]["material_version"] == 2
    assert "homework" in rows[0]["quote"]


def test_evidence_case_isolation(store):
    store.create_case("case-a")
    store.create_case("case-b")
    case_a = store.case("case-a")
    case_b = store.case("case-b")
    _seed_material(case_a)
    _seed_material(case_b, text="Case B sentence about the school bus.\n")
    case_a.refresh_evidence(RuleExtractor())
    case_b.refresh_evidence(RuleExtractor())
    assert {row["case_id"] for row in _rows(store, "case-a")} == {"case-a"}
    assert all("school bus" not in row["quote"] for row in _rows(store, "case-a"))


def test_needs_extraction_flag(case):
    _seed_material(case)
    assert case.evidence_needs_extraction() is True
    case.refresh_evidence(RuleExtractor())
    assert case.evidence_needs_extraction() is False


# -- stable ids and corrections (the two required tests) -----------------------


def test_correction_survives_rules_change(case, store):
    """Alex test 1: same span, new rules -> same id, her choice unchanged."""
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    items = case.list_evidence()
    weather = next(i for i in items if "weather" in i["quote"])
    assert weather["category"] == "uncategorized"
    case.set_evidence_choice(weather["id"], category="other", set_category=True)

    # rule-2: "weather" now maps to daily_living.
    changed = CategorizeRules(
        version="rule-2",
        categories=(
            CategoryRule("daily_living", "Daily living & function", __import__("re").compile("weather")),
            *default_rules().categories,
        ),
        roles=default_rules().roles,
    )
    case.refresh_evidence(RuleExtractor(), changed)

    after = {i["id"]: i for i in case.list_evidence()}
    same = after[weather["id"]]  # stable id: identical across rule versions
    assert same["category"] == "other"  # her choice is never overwritten
    assert same["category_set_by"] == "clinician"
    # With her choice in effect the reason is about HER choice; the rule's
    # keyword reason (updated by rule-2) stays on the suggestion fields.
    assert same["category_reason"] == "You chose this category."
    assert same["suggested_category"] == "daily_living"
    assert same["suggested_category_reason"].startswith("The text mentions")
    assert "weather" in same["suggested_category_reason"]
    row = store._connect().execute(
        "SELECT rules_version, suggested_category FROM evidence"
        " WHERE case_id = 'case-a' AND evidence_id = ?",
        (weather["id"],),
    ).fetchone()
    assert row["rules_version"] == "rule-2"
    assert row["suggested_category"] == "daily_living"


def test_superseded_corrected_item_stays_and_uncorrected_hides(case, store):
    """Alex test 2: new rules drop a span -> corrected row kept (flagged),
    uncorrected row hidden from the list but still in the table."""
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    items = case.list_evidence()
    assert len(items) == 2
    weather = next(i for i in items if "weather" in i["quote"])
    teacher = next(i for i in items if "Teacher" in i["quote"])
    case.set_evidence_choice(weather["id"], category="other", set_category=True)

    class SkipWeatherExtractor(RuleExtractor):
        """Simulates new rules that no longer produce the weather span."""

        def extract(self, material):
            return [
                candidate
                for candidate in super().extract(material)
                if "weather" not in candidate.quote
            ]

    case.refresh_evidence(SkipWeatherExtractor())

    listed = {i["id"]: i for i in case.list_evidence()}
    # The corrected item stays visible although its span is gone (flagged);
    # the still-produced uncorrected item stays listed as a normal active row.
    assert weather["id"] in listed
    assert listed[weather["id"]]["kept_because_corrected"] is True
    assert listed[weather["id"]]["category"] == "other"
    assert teacher["id"] in listed
    assert listed[teacher["id"]]["kept_because_corrected"] is False
    statuses = {
        row["evidence_id"]: row["status"] for row in _rows(store)
    }
    assert statuses[weather["id"]] == "superseded"  # row never deleted
    assert statuses[teacher["id"]] == "active"


def test_superseded_uncorrected_item_hides_but_row_survives(case, store):
    """The mirror case: an uncorrected item whose span disappears is hidden
    from the list, but its row still exists with status superseded."""
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    weather = next(i for i in case.list_evidence() if "weather" in i["quote"])

    class SkipWeatherExtractor(RuleExtractor):
        def extract(self, material):
            return [
                candidate
                for candidate in super().extract(material)
                if "weather" not in candidate.quote
            ]

    case.refresh_evidence(SkipWeatherExtractor())
    listed_ids = {i["id"] for i in case.list_evidence()}
    assert weather["id"] not in listed_ids
    row = store._connect().execute(
        "SELECT status FROM evidence WHERE case_id = 'case-a' AND evidence_id = ?",
        (weather["id"],),
    ).fetchone()
    assert row["status"] == "superseded"


def test_stable_id_depends_only_on_location(case, store):
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    first = {row["evidence_id"] for row in _rows(store)}
    # A different rules version cannot change the ids of the same spans.
    changed = CategorizeRules(
        version="rule-9", categories=(), roles=()
    )
    case.refresh_evidence(RuleExtractor(), changed)
    second = {row["evidence_id"] for row in _rows(store)}
    assert first == second


# -- corrections ----------------------------------------------------------------


def test_set_evidence_choice_reset_and_audit(case, store):
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    case.set_evidence_choice(item["id"], category="other", set_category=True)
    audits = _audit_actions(store, "evidence.categorize")
    assert len(audits) == 1
    assert audits[0]["object_type"] == "evidence"
    assert audits[0]["object_id"] == item["id"]
    assert audits[0]["content_hash"] is None  # no text in the audit row
    # Null resets to the suggestion.
    row = case.set_evidence_choice(item["id"], category=None, set_category=True)
    assert row["category"] is None
    assert len(_audit_actions(store, "evidence.categorize")) == 2
    # Setting the same value twice writes no extra audit row.
    case.set_evidence_choice(item["id"], category=None, set_category=True)
    assert len(_audit_actions(store, "evidence.categorize")) == 2
    ok, _, _ = verify_audit_chain(store)
    assert ok


def test_set_evidence_choice_role_audit(case, store):
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    case.set_evidence_choice(item["id"], role="caregiver", set_role=True)
    audits = _audit_actions(store, "evidence.set_role")
    assert len(audits) == 1
    assert audits[0]["object_id"] == item["id"]
    assert audits[0]["content_hash"] is None


def test_set_evidence_choice_validation(case):
    _seed_material(case)
    case.refresh_evidence(RuleExtractor())
    item = case.list_evidence()[0]
    with pytest.raises(ValueError):
        case.set_evidence_choice(item["id"], category="diagnosis", set_category=True)
    with pytest.raises(ValueError):
        case.set_evidence_choice(item["id"], role="parent", set_role=True)
    with pytest.raises(KeyError):
        case.set_evidence_choice("ev_doesnotexist", category="other", set_category=True)


# -- performance guard (PT-07 round 3) ----------------------------------------


def test_refresh_and_list_scale_to_50k_paragraphs(case, store):
    """50,000 short paragraphs: refresh + list each finish in < 10 s and a
    second refresh is a true no-op (no new audit rows)."""
    import time

    paragraphs = [
        Passage(id=f"p{i:05d}", text=f"Teacher note number {i} about class.")
        for i in range(1, 50_001)
    ]
    case.import_material(
        material_id="bulk", title="Bulk", provider="synthetic",
        date="2026-11-24", passages=paragraphs,
    )

    start = time.perf_counter()
    case.refresh_evidence(RuleExtractor())
    refresh_seconds = time.perf_counter() - start

    start = time.perf_counter()
    items = case.list_evidence()
    list_seconds = time.perf_counter() - start

    assert len(items) == 50_000
    assert items[0]["paragraph"] == 1
    assert items[-1]["paragraph"] == 50_000
    assert refresh_seconds < 10, f"refresh took {refresh_seconds:.2f}s"
    assert list_seconds < 10, f"list took {list_seconds:.2f}s"

    audits_before = len(_audit_actions(store, "evidence.extract"))
    start = time.perf_counter()
    case.refresh_evidence(RuleExtractor())
    rerun_seconds = time.perf_counter() - start
    assert rerun_seconds < 10, f"idempotent refresh took {rerun_seconds:.2f}s"
    assert len(_audit_actions(store, "evidence.extract")) == audits_before

    print(
        f"\nperf: refresh={refresh_seconds:.2f}s list={list_seconds:.2f}s "
        f"rerun={rerun_seconds:.2f}s"
    )
