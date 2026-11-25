"""PT-20 chunk 2 (GROK-51): suggestions cite stored sentence evidence.

Covers both workspace backends: suggest_claims emits one suggestion per
passage that has stored active evidence (never an empty evidence_ids list,
never a paragraph-only suggestion), accept_suggestion requires at least one
id that resolves against the stored set, and the HTTP routes return the ids
and reject unknown / cross-case / empty lists without revealing whether an
id exists on another case.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from psychtool.core.extract import RuleExtractor
from psychtool.core.intake_claims import (
    INVALID_EVIDENCE_IDS,
    accept_suggestion,
    suggest_claims,
)
from psychtool.core.workspace import Passage, import_material, init_workspace
from psychtool.server.app import create_app
from psychtool.store.sqlite_store import SqliteStore
from tests.conftest import build_client

PASSAGE_ONE = "Teacher says he reads slowly in class."
PASSAGE_TWO = "He rides his bike after school."


# -- CaseStore path ---------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


@pytest.fixture
def case(store):
    store.create_case("case-a")
    return store.case("case-a")


def _import_two_passages(case, material_id="m1"):
    return case.import_material(
        material_id=material_id, title="Note", provider="synthetic",
        date="2026-11-24",
        passages=[
            Passage(id="p001", text=PASSAGE_ONE),
            Passage(id="p002", text=PASSAGE_TWO),
        ],
    )


def test_suggest_claims_cites_stored_active_evidence_ids(case):
    _import_two_passages(case)
    case.refresh_evidence(RuleExtractor())
    stored = case.active_evidence_ids_by_passage("m1", 1)
    suggestions = suggest_claims(case, "m1", provider_role="self_report")
    assert [s.source_passage_id for s in suggestions] == ["p001", "p002"]
    for suggestion in suggestions:
        assert suggestion.evidence_ids == stored[suggestion.source_passage_id]
        assert suggestion.evidence_ids  # never empty
        assert all(evidence_id.startswith("ev_") for evidence_id in suggestion.evidence_ids)
        # The paragraph locator stays as the grouping.
        assert suggestion.source_document_id == "m1"
        assert suggestion.source_version == 1
        assert suggestion.id == f"m1-v1-{suggestion.source_passage_id}"


def test_passage_without_active_evidence_produces_no_suggestion(case):
    _import_two_passages(case)
    case.refresh_evidence(RuleExtractor())
    # Supersede every evidence row of p002: it must drop out of suggestions.
    p002_ids = case.active_evidence_ids_by_passage("m1", 1)["p002"]
    with case._store.transaction() as connection:
        for evidence_id in p002_ids:
            connection.execute(
                "UPDATE evidence SET status = 'superseded'"
                " WHERE case_id = 'case-a' AND evidence_id = ?",
                (evidence_id,),
            )
    suggestions = suggest_claims(case, "m1", provider_role="self_report")
    assert [s.source_passage_id for s in suggestions] == ["p001"]


def test_suggest_claims_without_any_stored_evidence_is_empty(case):
    _import_two_passages(case)
    assert case.list_evidence() == []
    assert suggest_claims(case, "m1", provider_role="self_report") == []


def test_accept_happy_path_persists_evidence_ids(case):
    _import_two_passages(case)
    case.refresh_evidence(RuleExtractor())
    suggestion = suggest_claims(case, "m1", provider_role="self_report")[0]
    claim = accept_suggestion(case, suggestion)
    assert claim.evidence_ids == suggestion.evidence_ids
    assert case.get_claim(claim.id).evidence_ids == suggestion.evidence_ids


def test_accept_rejects_empty_evidence_ids(case):
    _import_two_passages(case)
    case.refresh_evidence(RuleExtractor())
    suggestion = suggest_claims(case, "m1", provider_role="self_report")[0]
    suggestion.evidence_ids = []
    with pytest.raises(ValueError, match=INVALID_EVIDENCE_IDS):
        accept_suggestion(case, suggestion)


def test_accept_rejects_unknown_evidence_id(case):
    _import_two_passages(case)
    case.refresh_evidence(RuleExtractor())
    suggestion = suggest_claims(case, "m1", provider_role="self_report")[0]
    suggestion.evidence_ids = ["ev_doesnotexist000000000000"]
    with pytest.raises(ValueError, match=INVALID_EVIDENCE_IDS):
        accept_suggestion(case, suggestion)


def test_accept_rejects_another_cases_evidence_id(store):
    store.create_case("case-a")
    store.create_case("case-b")
    case_a = store.case("case-a")
    case_b = store.case("case-b")
    _import_two_passages(case_a)
    _import_two_passages(case_b)
    case_a.refresh_evidence(RuleExtractor())
    case_b.refresh_evidence(RuleExtractor())
    suggestion = suggest_claims(case_a, "m1", provider_role="self_report")[0]
    b_ids = case_b.active_evidence_ids_by_passage("m1", 1)["p001"]
    assert b_ids
    suggestion.evidence_ids = b_ids
    with pytest.raises(ValueError) as excinfo:
        accept_suggestion(case_a, suggestion)
    # The message is fixed and never reveals the id exists on another case.
    assert str(excinfo.value) == INVALID_EVIDENCE_IDS


def test_accept_still_enforces_passage_and_version_checks(case):
    _import_two_passages(case)
    case.refresh_evidence(RuleExtractor())
    suggestion = suggest_claims(case, "m1", provider_role="self_report")[0]
    stale = suggestion.model_copy(update={"source_version": 99})
    with pytest.raises(ValueError, match="version changed"):
        accept_suggestion(case, stale)
    changed = suggestion.model_copy(update={"source_text": "tampered"})
    with pytest.raises(ValueError, match="passage changed"):
        accept_suggestion(case, changed)


# -- file-workspace path ----------------------------------------------------------


def test_file_workspace_suggestions_cite_persisted_evidence(tmp_path):
    ws = init_workspace(tmp_path / "case", case_id="case")
    import_material(
        ws, material_id="intake", title="Intake", provider="client",
        date="2026-11-01", text="Reported trouble sleeping.\n\nStart date unknown.",
    )
    candidates = suggest_claims(ws, "intake", provider_role="self_report")
    assert [c.source_passage_id for c in candidates] == ["p001", "p002"]
    # Evidence was persisted on first suggest; ids are stable across calls.
    again = suggest_claims(ws, "intake", provider_role="self_report")
    assert [c.evidence_ids for c in candidates] == [c.evidence_ids for c in again]
    for candidate in candidates:
        assert candidate.evidence_ids
        assert all(evidence_id.startswith("ev_") for evidence_id in candidate.evidence_ids)
    candidates[0].topic = "sleep"
    claim = accept_suggestion(ws, candidates[0])
    assert claim.evidence_ids == candidates[0].evidence_ids
    assert claim.topic == "sleep"


def test_file_workspace_accept_rejects_unknown_and_empty_ids(tmp_path):
    ws = init_workspace(tmp_path / "case", case_id="case")
    import_material(
        ws, material_id="intake", title="Intake", provider="client",
        date="2026-11-01", text="Reported trouble sleeping.",
    )
    candidate = suggest_claims(ws, "intake", provider_role="self_report")[0]
    empty = candidate.model_copy(update={"evidence_ids": []})
    with pytest.raises(ValueError, match=INVALID_EVIDENCE_IDS):
        accept_suggestion(ws, empty)
    unknown = candidate.model_copy(update={"evidence_ids": ["ev_nope"]})
    with pytest.raises(ValueError, match=INVALID_EVIDENCE_IDS):
        accept_suggestion(ws, unknown)


# -- HTTP routes ------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)
    store.create_case("case-a")
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(db_path))
    return build_client(create_app())


def _paste(client, text="Synthetic observation paragraph.", material_id="doc-1"):
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": material_id,
            "title": "Synthetic source",
            "provider": "synthetic",
            "date": "2026-11-20",
            "text": text,
            "synthetic_confirmed": True,
        },
    )
    assert response.status_code == 200
    return response


def _suggestions(client, material_id="doc-1"):
    response = client.get(
        f"/api/workspaces/case-a/materials/{material_id}/suggestions",
        params={"provider_role": "self_report"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_get_suggestions_returns_evidence_ids(client):
    _paste(client)
    suggestions = _suggestions(client)
    assert len(suggestions) == 1
    assert suggestions[0]["evidence_ids"]
    assert all(evidence_id.startswith("ev_") for evidence_id in suggestions[0]["evidence_ids"])


def test_post_claims_happy_path_returns_evidence_ids(client):
    _paste(client)
    suggestion = _suggestions(client)[0]
    response = client.post("/api/workspaces/case-a/claims", json=suggestion)
    assert response.status_code == 200, response.text
    assert response.json()["evidence_ids"] == suggestion["evidence_ids"]


def test_post_claims_rejects_empty_evidence_ids(client):
    _paste(client)
    suggestion = _suggestions(client)[0]
    suggestion["evidence_ids"] = []
    response = client.post("/api/workspaces/case-a/claims", json=suggestion)
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid claim"


def test_post_claims_rejects_unknown_evidence_id(client):
    _paste(client)
    suggestion = _suggestions(client)[0]
    suggestion["evidence_ids"] = ["ev_doesnotexist000000000000"]
    response = client.post("/api/workspaces/case-a/claims", json=suggestion)
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid claim"


def test_post_claims_rejects_another_cases_evidence_id(client):
    _paste(client)
    suggestion = _suggestions(client)[0]
    # A second case with its own stored evidence.
    assert client.post("/api/workspaces", json={"case_id": "case-b"}).status_code == 201
    response = client.post(
        "/api/workspaces/case-b/materials/paste",
        json={
            "material_id": "doc-1",
            "title": "Synthetic source",
            "provider": "synthetic",
            "date": "2026-11-20",
            "text": "Case B synthetic observation paragraph.",
            "synthetic_confirmed": True,
        },
    )
    assert response.status_code == 200
    b_suggestions = client.get(
        "/api/workspaces/case-b/materials/doc-1/suggestions",
        params={"provider_role": "self_report"},
    ).json()
    b_ids = b_suggestions[0]["evidence_ids"]
    assert b_ids
    forged = dict(suggestion, evidence_ids=b_ids)
    response = client.post("/api/workspaces/case-a/claims", json=forged)
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid claim"
    # Nothing was written to case A.
    assert client.get("/api/workspaces/case-a/claims").json() == []
