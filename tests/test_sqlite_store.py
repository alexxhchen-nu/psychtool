"""Store unit tests: case registry, versioning, locks, and transactions."""

import sqlite3
import threading

import pytest

from psychtool.core.egress import (
    EgressRequest,
    EgressStateError,
    OutboundEnvelope,
)
from psychtool.core.workspace import Passage
from psychtool.store.sqlite_store import (
    CaseExistsError,
    SqliteStore,
    UnknownCaseError,
)


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


def _request(case_id: str, request_id: str = "req-1") -> EgressRequest:
    return EgressRequest(
        request_id=request_id,
        workspace_id=case_id,
        purpose="section_generation",
        data_tier="synthetic",
        provider_base_url="http://127.0.0.1:9/v1",
        envelope=OutboundEnvelope(
            model="m", messages=[{"role": "user", "content": "synthetic"}]
        ),
        source_refs=[],
        identifier_categories=[],
        content_hash="0" * 64,
        status="prepared",
        prepared_at="2026-11-24T00:00:00+00:00",
    )


def test_create_and_list_cases(store):
    store.create_case("case-a")
    store.create_case("case-b")
    assert store.list_cases() == ["case-a", "case-b"]
    assert store.case_exists("case-a") is True
    assert store.case_exists("case-c") is False


def test_duplicate_case_raises(store):
    store.create_case("case-a")
    with pytest.raises(CaseExistsError):
        store.create_case("case-a")


def test_unknown_case_binding_raises(store):
    with pytest.raises(UnknownCaseError):
        store.case("case-a")


@pytest.mark.parametrize("bad", ["", "..", "../x", "a/b", " spaced", "-lead", "x" * 65, "case.1", "%", "_", "A' OR '1'='1"])
def test_case_id_validation_rejects_hostile_ids(store, bad):
    with pytest.raises(ValueError):
        store.create_case(bad)


def test_material_versioning_is_append_only(store):
    store.create_case("case-a")
    case = store.case("case-a")
    first = case.import_material(
        material_id="m1", title="t", provider="p", date="d",
        passages=[Passage(id="p001", text="v1 text")],
    )
    second = case.import_material(
        material_id="m1", title="t", provider="p", date="d",
        passages=[Passage(id="p001", text="v2 text")],
    )
    assert first.version == 1
    assert second.version == 2
    assert case.latest_material_version("m1") == 2
    assert case.get_material("m1").passages[0].text == "v2 text"
    assert case.get_material("m1", version=1).passages[0].text == "v1 text"


def test_known_names_roundtrip_sorted_deduped(store):
    store.create_case("case-a")
    case = store.case("case-a")
    assert case.get_known_names() == ()
    result = case.set_known_names(["Jane Doe", "Dr. Smith", "jane doe"])
    assert result == ("Dr. Smith", "Jane Doe")
    assert case.get_known_names() == ("Dr. Smith", "Jane Doe")


def test_egress_request_roundtrip(store):
    store.create_case("case-a")
    case = store.case("case-a")
    request = _request("case-a")
    case.save_egress_request(request)
    loaded = case.get_egress_request("req-1")
    assert loaded == request


def test_egress_request_scoped_to_case(store):
    store.create_case("case-a")
    store.create_case("case-b")
    store.case("case-a").save_egress_request(_request("case-a"))
    with pytest.raises(FileNotFoundError):
        store.case("case-b").get_egress_request("req-1")


def test_egress_request_rejects_other_case(store):
    store.create_case("case-a")
    store.create_case("case-b")
    with pytest.raises(ValueError):
        store.case("case-a").save_egress_request(_request("case-b"))


def test_transition_lock_is_exclusive_and_owner_checked(store):
    store.create_case("case-a")
    case = store.case("case-a")
    case.save_egress_request(_request("case-a"))
    assert case.try_acquire_transition_lock("req-1", "owner-1") is True
    assert case.try_acquire_transition_lock("req-1", "owner-2") is False
    # A non-owner cannot clear someone else's lock.
    with pytest.raises(EgressStateError):
        case.release_transition_lock("req-1", "owner-2")
    case.release_transition_lock("req-1", "owner-1")
    assert case.try_acquire_transition_lock("req-1", "owner-2") is True


def test_send_lock_is_send_once(store):
    store.create_case("case-a")
    case = store.case("case-a")
    case.save_egress_request(_request("case-a"))
    assert case.try_acquire_send_lock("req-1", "owner-1") is True
    assert case.try_acquire_send_lock("req-1", "owner-2") is False
    # Re-saving the request (state transition) keeps the send lock held.
    case.save_egress_request(_request("case-a"))
    assert case.try_acquire_send_lock("req-1", "owner-3") is False
    case.release_send_lock("req-1", "owner-1")
    assert case.try_acquire_send_lock("req-1", "owner-2") is True


def test_transaction_rolls_back_partial_writes(store):
    store.create_case("case-a")
    case = store.case("case-a")
    with pytest.raises(RuntimeError):
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO known_names (case_id, name) VALUES (?, ?)",
                ("case-a", "Jane Doe"),
            )
            raise RuntimeError("boom")
    assert case.get_known_names() == ()


def test_concurrent_case_creation_yields_one_winner(tmp_path):
    path = tmp_path / "psychtool.db"
    SqliteStore(path)  # initialize schema before threads race
    outcomes: list[str] = []
    barrier = threading.Barrier(4)

    def create():
        local = SqliteStore(path)
        barrier.wait(timeout=10)
        try:
            local.create_case("case-race")
            outcomes.append("created")
        except CaseExistsError:
            outcomes.append("exists")

    threads = [threading.Thread(target=create) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["created", "exists", "exists", "exists"]


def test_schema_uses_wal_and_full_sync(store):
    mode = store._connect().execute("PRAGMA journal_mode").fetchone()[0]
    sync = store._connect().execute("PRAGMA synchronous").fetchone()[0]
    assert mode.lower() == "wal"
    assert sync == 2  # FULL


def test_foreign_keys_enforced(store):
    store.create_case("case-a")
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO known_names (case_id, name) VALUES (?, ?)",
                ("no-such-case", "Jane Doe"),
            )


def test_claim_cannot_reference_another_cases_passage(store):
    """Structural isolation: the claims->passages composite FK rejects a raw
    cross-case source reference even when written with direct SQL."""
    from psychtool.core.workspace import Passage

    store.create_case("case-a")
    store.create_case("case-b")
    store.case("case-b").import_material(
        material_id="m1", title="t", provider="p", date="d",
        passages=[Passage(id="p001", text="B text")],
    )
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO claims"
                " (case_id, claim_id, version, source_document_id, source_version,"
                "  source_passage_id, provider_role, observation_setting, record_time,"
                "  event_time, category, topic, text, verification_status)"
                " VALUES ('case-a', 'c1', 1, 'm1', 1, 'p001', 'self_report',"
                "         'intake', 'd', NULL, 'client_statement', 'history',"
                "         'cross-case attempt', 'pending')",
            )


def test_claim_cannot_reference_missing_passage(store):
    store.create_case("case-a")
    case = store.case("case-a")
    with pytest.raises(sqlite3.IntegrityError):
        case.add_claim(
            claim_id="c1",
            source_document_id="ghost",
            source_version=1,
            source_passage_id="p001",
            provider_role="self_report",
            observation_setting="intake",
            record_time="d",
            category="client_statement",
            topic="history",
            text="no such passage",
        )


def test_egress_status_check_covers_model_literal(store):
    """The DB CHECK must accept exactly the statuses the model can hold."""
    import typing

    from psychtool.core.egress import EgressStatus

    model_statuses = set(typing.get_args(EgressStatus))
    row = store._connect().execute(
        "SELECT sql FROM sqlite_master WHERE name = 'egress_requests'"
    ).fetchone()
    import re

    match = re.search(r"status IN \(([^)]+)\)", row[0])
    assert match is not None
    db_statuses = {s.strip().strip("'") for s in match.group(1).split(",")}
    assert db_statuses == model_statuses
