"""PT-20 chunk 1 (GROK-51): claim_evidence schema v7 migration + store tests.

The migration test builds a genuine v6 database (pre-v7 DDL, real rows) and
proves the v6->v7 step links each claim to exactly the *active* evidence rows
on its cited passage — never superseded rows, never another case's evidence,
never invented rows — while leaving claim text/provenance and the audit chain
untouched. The store tests cover add_claim with evidence_ids: valid same-case
ids persist and hydrate; unknown or cross-case ids raise; an empty list stays
allowed at the store layer for this chunk.
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest

from psychtool.core.extract import RuleExtractor
from psychtool.core.workspace import Passage
from psychtool.store.audit import GENESIS_PREV_HASH, compute_entry_hash, verify_audit_chain
from psychtool.store.sqlite_store import SqliteStore, _SCHEMA_VERSION

# The v6 table shapes this fixture depends on. The DDL snapshot below is the
# pre-v7 _SCHEMA_STATEMENTS (v6 materials.kind, dimensions, evidence dim
# columns, audit value) minus the v7 claim_evidence table; asserting the
# relevant columns exist keeps the fixture honest if the schema drifts.
_PASSAGE_TEXT = "Teacher says he reads slowly in class."
_OTHER_PASSAGE_TEXT = "The weather was cloudy that week."
_CLAIM_TEXT = "Teacher says he reads slowly in class."


def _evidence_id(
    case_id: str,
    material_id: str,
    material_version: int,
    passage_id: str,
    start: int,
    end: int,
) -> str:
    """Same location-derived id the store computes (never rules-dependent)."""
    payload = "\x1f".join(
        (case_id, material_id, str(material_version), passage_id, str(start), str(end))
    )
    return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _quote_span(quote: str, passage: str) -> tuple[int, int]:
    start = passage.index(quote)
    return start, start + len(quote)


def _insert_evidence(
    raw: sqlite3.Connection,
    *,
    case_id: str,
    evidence_id: str,
    material_id: str,
    material_version: int,
    passage_id: str,
    start: int,
    end: int,
    quote: str,
    status: str,
) -> None:
    raw.execute(
        "INSERT INTO evidence (case_id, evidence_id, material_id, material_version,"
        " passage_id, start, end, quote, suggested_category, category_reason,"
        " suggested_role, role_reason, category, role, status, rules_version,"
        " suggested_dimension_id, dim_state_suggested, dim_reason,"
        " dimension_choice, dimension_id, dim_rules_version)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uncategorized',"
        " 'No words in the text indicate a category, so the system does not"
        " choose for you.', 'to_confirm',"
        " 'No words in the text indicate a source role, so the system does"
        " not choose for you.', NULL, NULL, ?, 'rule-1', NULL, NULL, NULL,"
        " NULL, NULL, NULL)",
        (
            case_id,
            evidence_id,
            material_id,
            material_version,
            passage_id,
            start,
            end,
            quote,
            status,
        ),
    )


def _insert_audit_row(
    raw: sqlite3.Connection,
    *,
    case_id: str,
    action: str,
    object_type: str,
    object_id: str,
    item_count: int | None = None,
    prev_hash: str = GENESIS_PREV_HASH,
) -> str:
    """Append one hashed audit row; returns its entry_hash for chaining."""
    fields = {
        "case_id": case_id,
        "ts": "2026-01-01T00:00:00+00:00",
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "content_hash": None,
        "destination": None,
        "prev_hash": prev_hash,
    }
    if item_count is not None:
        fields["item_count"] = item_count
    fields["entry_hash"] = compute_entry_hash(fields)
    columns = (
        "case_id, ts, action, object_type, object_id, content_hash,"
        " destination, prev_hash, entry_hash"
        + (", item_count" if item_count is not None else "")
    )
    placeholders = (
        ":case_id, :ts, :action, :object_type, :object_id, :content_hash,"
        " :destination, :prev_hash, :entry_hash"
        + (", :item_count" if item_count is not None else "")
    )
    raw.execute(
        f"INSERT INTO audit_log ({columns}) VALUES ({placeholders})", fields
    )
    return fields["entry_hash"]


def _build_v6_database(db) -> dict[str, str]:
    """A genuine v6 database with real rows: current pre-v7 DDL, user_version=6.

    Case-a: one material, one passage, two ACTIVE sentence evidence rows whose
    quotes are verbatim slices of that passage, plus one SUPERSEDED row on the
    same passage, and one claim citing the passage. Case-b: its own material,
    passage and active evidence (the migrator must not attach cross-case ids).
    One real hashed audit row per case so verify_audit_chain has a chain.
    Returns the evidence ids the migration must link / must not link.
    """
    from psychtool.store.sqlite_store import _SCHEMA_STATEMENTS

    raw = sqlite3.connect(db)
    raw.execute("PRAGMA foreign_keys = ON")
    for statement in _SCHEMA_STATEMENTS:
        if "CREATE TABLE IF NOT EXISTS claim_evidence" in statement:
            continue
        raw.execute(statement)
    # Guard the snapshot: the v6 shape this fixture relies on must be present.
    materials_cols = {
        row[1] for row in raw.execute("PRAGMA table_info(materials)")
    }
    evidence_cols = {
        row[1] for row in raw.execute("PRAGMA table_info(evidence)")
    }
    audit_cols = {row[1] for row in raw.execute("PRAGMA table_info(audit_log)")}
    assert "kind" in materials_cols
    assert {"suggested_dimension_id", "dimension_choice", "dim_rules_version"} <= evidence_cols
    assert "value" in audit_cols

    for case_id in ("case-a", "case-b"):
        raw.execute(
            "INSERT INTO cases VALUES (?, 'synthetic', '2026-01-01', NULL)",
            (case_id,),
        )
    # case-a: one material (v1), one passage.
    raw.execute(
        "INSERT INTO materials (case_id, material_id, version, title, provider,"
        " date, kind) VALUES ('case-a', 'doc', 1, 't', 'p', '2026-01-01', 'case')"
    )
    raw.execute(
        "INSERT INTO passages VALUES ('case-a', 'doc', 1, 'p001', 1, ?)",
        (_PASSAGE_TEXT,),
    )
    # Two ACTIVE evidence rows on p001, quotes verbatim slices of the passage.
    quote_one = "Teacher says he reads slowly"
    quote_two = "reads slowly in class."
    ev_active_one = _evidence_id("case-a", "doc", 1, "p001", *_quote_span(quote_one, _PASSAGE_TEXT))
    ev_active_two = _evidence_id("case-a", "doc", 1, "p001", *_quote_span(quote_two, _PASSAGE_TEXT))
    # One SUPERSEDED row on the same passage — must NOT be linked.
    quote_old = "Teacher says"
    ev_superseded = _evidence_id("case-a", "doc", 1, "p001", *_quote_span(quote_old, _PASSAGE_TEXT))
    _insert_evidence(
        raw, case_id="case-a", evidence_id=ev_active_one, material_id="doc",
        material_version=1, passage_id="p001",
        start=_quote_span(quote_one, _PASSAGE_TEXT)[0],
        end=_quote_span(quote_one, _PASSAGE_TEXT)[1],
        quote=quote_one, status="active",
    )
    _insert_evidence(
        raw, case_id="case-a", evidence_id=ev_active_two, material_id="doc",
        material_version=1, passage_id="p001",
        start=_quote_span(quote_two, _PASSAGE_TEXT)[0],
        end=_quote_span(quote_two, _PASSAGE_TEXT)[1],
        quote=quote_two, status="active",
    )
    _insert_evidence(
        raw, case_id="case-a", evidence_id=ev_superseded, material_id="doc",
        material_version=1, passage_id="p001",
        start=_quote_span(quote_old, _PASSAGE_TEXT)[0],
        end=_quote_span(quote_old, _PASSAGE_TEXT)[1],
        quote=quote_old, status="superseded",
    )
    # The pre-v7 claim citing p001.
    raw.execute(
        "INSERT INTO claims (case_id, claim_id, version, source_document_id,"
        " source_version, source_passage_id, provider_role,"
        " observation_setting, record_time, event_time, category, topic,"
        " text, verification_status)"
        " VALUES ('case-a', 'c1', 1, 'doc', 1, 'p001', 'self_report',"
        " 'intake', '2026-01-01', NULL, 'client_statement', 'history', ?,"
        " 'pending')",
        (_CLAIM_TEXT,),
    )
    # case-b: its own material/passage/active evidence — never linked to c1.
    raw.execute(
        "INSERT INTO materials (case_id, material_id, version, title, provider,"
        " date, kind) VALUES ('case-b', 'doc', 1, 't', 'p', '2026-01-01', 'case')"
    )
    raw.execute(
        "INSERT INTO passages VALUES ('case-b', 'doc', 1, 'p001', 1, ?)",
        (_OTHER_PASSAGE_TEXT,),
    )
    quote_b = "The weather was cloudy"
    ev_case_b = _evidence_id("case-b", "doc", 1, "p001", *_quote_span(quote_b, _OTHER_PASSAGE_TEXT))
    _insert_evidence(
        raw, case_id="case-b", evidence_id=ev_case_b, material_id="doc",
        material_version=1, passage_id="p001",
        start=_quote_span(quote_b, _OTHER_PASSAGE_TEXT)[0],
        end=_quote_span(quote_b, _OTHER_PASSAGE_TEXT)[1],
        quote=quote_b, status="active",
    )
    # A short real audit chain (hashed rows only, never text).
    prev = _insert_audit_row(
        raw, case_id="case-a", action="case.create", object_type="case",
        object_id="case-a",
    )
    prev = _insert_audit_row(
        raw, case_id="case-a", action="material.import", object_type="material",
        object_id="doc", item_count=None, prev_hash=prev,
    )
    _insert_audit_row(
        raw, case_id="case-a", action="claim.accept", object_type="claim",
        object_id="c1", prev_hash=prev,
    )
    raw.execute("PRAGMA user_version = 6")
    raw.commit()
    raw.close()
    return {
        "ev_active_one": ev_active_one,
        "ev_active_two": ev_active_two,
        "ev_superseded": ev_superseded,
        "ev_case_b": ev_case_b,
    }


def test_v6_database_migrates_to_v7_with_existing_data(tmp_path):
    db = tmp_path / "psychtool.db"
    ids = _build_v6_database(db)

    store = SqliteStore(db)
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION

    expected_linked = sorted([ids["ev_active_one"], ids["ev_active_two"]])
    linked = [
        row[0]
        for row in connection.execute(
            "SELECT evidence_id FROM claim_evidence"
            " WHERE case_id = 'case-a' AND claim_id = 'c1' AND version = 1"
            " ORDER BY evidence_id"
        ).fetchall()
    ]
    assert linked == expected_linked
    # The superseded row on the same passage is never linked.
    assert ids["ev_superseded"] not in linked
    # No cross-case id is ever attached.
    assert ids["ev_case_b"] not in linked
    assert connection.execute(
        "SELECT COUNT(*) FROM claim_evidence WHERE case_id = 'case-b'"
    ).fetchone()[0] == 0

    # Claim text/provenance are unchanged by the migration.
    claim = connection.execute(
        "SELECT source_document_id, source_version, source_passage_id,"
        " provider_role, observation_setting, record_time, event_time,"
        " category, topic, text, verification_status"
        " FROM claims WHERE case_id = 'case-a' AND claim_id = 'c1' AND version = 1"
    ).fetchone()
    assert tuple(claim) == (
        "doc", 1, "p001", "self_report", "intake", "2026-01-01", None,
        "client_statement", "history", _CLAIM_TEXT, "pending",
    )
    # Evidence rows themselves are untouched (same count, same statuses).
    statuses = {
        row["evidence_id"]: row["status"]
        for row in connection.execute(
            "SELECT evidence_id, status FROM evidence WHERE case_id = 'case-a'"
        ).fetchall()
    }
    assert statuses == {
        ids["ev_active_one"]: "active",
        ids["ev_active_two"]: "active",
        ids["ev_superseded"]: "superseded",
    }
    # The audit chain written before the migration still verifies.
    ok, count, bad = verify_audit_chain(store)
    assert (ok, count, bad) == (True, 3, None)

    # And the migrated claim hydrates through the store with its evidence ids.
    case = store.case("case-a")
    migrated = case.get_claim("c1")
    assert migrated.evidence_ids == expected_linked
    assert migrated.text == _CLAIM_TEXT
    assert case.list_claims()[0].evidence_ids == expected_linked


def test_v6_claim_without_evidence_gets_zero_junction_rows(tmp_path):
    """A claim whose passage has no active evidence stays unlinked — the
    migrator never invents evidence and never rewrites the claim."""
    db = tmp_path / "psychtool.db"
    from psychtool.store.sqlite_store import _SCHEMA_STATEMENTS

    raw = sqlite3.connect(db)
    for statement in _SCHEMA_STATEMENTS:
        if "CREATE TABLE IF NOT EXISTS claim_evidence" in statement:
            continue
        raw.execute(statement)
    raw.execute(
        "INSERT INTO cases VALUES ('case-a', 'synthetic', '2026-01-01', NULL)"
    )
    raw.execute(
        "INSERT INTO materials (case_id, material_id, version, title, provider,"
        " date, kind) VALUES ('case-a', 'doc', 1, 't', 'p', '2026-01-01', 'case')"
    )
    raw.execute(
        "INSERT INTO passages VALUES ('case-a', 'doc', 1, 'p001', 1, 'No evidence here.')"
    )
    raw.execute(
        "INSERT INTO claims (case_id, claim_id, version, source_document_id,"
        " source_version, source_passage_id, provider_role,"
        " observation_setting, record_time, event_time, category, topic,"
        " text, verification_status)"
        " VALUES ('case-a', 'c1', 1, 'doc', 1, 'p001', 'self_report',"
        " 'intake', '2026-01-01', NULL, 'client_statement', 'history',"
        " 'No evidence here.', 'pending')"
    )
    raw.execute("PRAGMA user_version = 6")
    raw.commit()
    raw.close()

    store = SqliteStore(db)
    connection = store._connect()
    assert connection.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
    assert connection.execute(
        "SELECT COUNT(*) FROM claim_evidence WHERE case_id = 'case-a'"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT text FROM claims WHERE case_id = 'case-a' AND claim_id = 'c1'"
    ).fetchone()[0] == "No evidence here."
    assert store.case("case-a").get_claim("c1").evidence_ids == []


# -- store-level add_claim with evidence_ids ------------------------------------


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


@pytest.fixture
def case(store):
    store.create_case("case-a")
    return store.case("case-a")


def _claim_fields(**over):
    fields = dict(
        source_document_id="m1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-11-24",
        category="client_statement",
        topic="history",
        text="Teacher says he reads slowly in class.",
    )
    fields.update(over)
    return fields


def _seed_material_with_evidence(case):
    """One material whose passage yields two active evidence rows."""
    case.import_material(
        material_id="m1", title="Note", provider="synthetic", date="2026-11-24",
        passages=[Passage(id="p001", text=_PASSAGE_TEXT)],
    )
    case.refresh_evidence(RuleExtractor())
    return [item["id"] for item in case.list_evidence()]


def test_add_claim_with_valid_evidence_ids_persists_and_lists(case):
    evidence_ids = _seed_material_with_evidence(case)
    claim = case.add_claim(
        claim_id="c1", **_claim_fields(evidence_ids=list(evidence_ids))
    )
    assert sorted(claim.evidence_ids) == sorted(evidence_ids)
    # Hydrated back through every read path.
    assert case.get_claim("c1").evidence_ids == sorted(evidence_ids)
    assert case.list_claims()[0].evidence_ids == sorted(evidence_ids)
    assert case.get_claim_version("c1", 1).evidence_ids == sorted(evidence_ids)


def test_add_claim_with_unknown_evidence_id_raises(case):
    _seed_material_with_evidence(case)
    with pytest.raises(ValueError, match="unknown evidence id"):
        case.add_claim(
            claim_id="c1", **_claim_fields(evidence_ids=["ev_doesnotexist"])
        )
    # The failed write rolled back: no claim row exists.
    with pytest.raises(KeyError):
        case.get_claim("c1")


def test_add_claim_rejects_another_cases_evidence_id(store):
    store.create_case("case-a")
    store.create_case("case-b")
    case_a = store.case("case-a")
    case_b = store.case("case-b")
    # Identical material/passage/text in both cases -> identical location ids
    # in the fixture sense, but each case has its OWN evidence rows.
    for case in (case_a, case_b):
        case.import_material(
            material_id="m1", title="Note", provider="synthetic",
            date="2026-11-24",
            passages=[Passage(id="p001", text=_PASSAGE_TEXT)],
        )
        case.refresh_evidence(RuleExtractor())
    b_ids = [item["id"] for item in case_b.list_evidence()]
    assert b_ids
    with pytest.raises(ValueError, match="unknown evidence id"):
        case_a.add_claim(claim_id="c1", **_claim_fields(evidence_ids=b_ids))


def test_add_claim_with_empty_evidence_ids_still_allowed(case):
    _seed_material_with_evidence(case)
    claim = case.add_claim(claim_id="c1", **_claim_fields(evidence_ids=[]))
    assert claim.evidence_ids == []
    assert case.get_claim("c1").evidence_ids == []
    # Omitting the field entirely behaves the same.
    claim2 = case.add_claim(claim_id="c2", **_claim_fields())
    assert claim2.evidence_ids == []


def test_mark_claim_status_carries_evidence_ids_forward(case):
    evidence_ids = _seed_material_with_evidence(case)
    case.add_claim(claim_id="c1", **_claim_fields(evidence_ids=list(evidence_ids)))
    updated = case.mark_claim_status("c1", "verified")
    assert updated.version == 2
    assert updated.evidence_ids == sorted(evidence_ids)
    assert case.get_claim_version("c1", 1).evidence_ids == sorted(evidence_ids)


def test_claim_evidence_composite_fk_blocks_cross_case_insert(store):
    """Raw SQL cannot attach another case's evidence either: the
    (case_id, evidence_id) FK rejects it structurally."""
    store.create_case("case-a")
    store.create_case("case-b")
    case_a = store.case("case-a")
    case_b = store.case("case-b")
    for case in (case_a, case_b):
        case.import_material(
            material_id="m1", title="Note", provider="synthetic",
            date="2026-11-24",
            passages=[Passage(id="p001", text=_PASSAGE_TEXT)],
        )
        case.refresh_evidence(RuleExtractor())
    b_id = case_b.list_evidence()[0]["id"]
    case_a.add_claim(claim_id="c1", **_claim_fields())
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO claim_evidence (case_id, claim_id, version, evidence_id)"
                " VALUES ('case-a', 'c1', 1, ?)",
                (b_id,),
            )
