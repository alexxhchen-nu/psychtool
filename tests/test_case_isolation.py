"""Adversarial case-isolation tests: one case can never reach another's rows.

Covers the API surface and the store directly: overlapping ids, cross-case
claim/egress/section access, unknown cases, and hostile case ids (SQL/SQLite
metacharacters and path traversal shapes) which must be rejected before any
query is built.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from psychtool.core.workspace import Passage
from psychtool.server.app import create_app
from psychtool.store.sqlite_store import SqliteStore, UnknownCaseError
from tests.conftest import build_client

B_MARKER = "B-ONLY-MARKER-STRING-9f2c"


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """Two cases, A and B, each with a material whose id overlaps (``m1``)."""
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)
    for case_id, text in (("case-a", "A intake paragraph."), ("case-b", B_MARKER)):
        store.create_case(case_id)
        case = store.case(case_id)
        case.import_material(
            material_id="m1", title=f"{case_id} intake", provider="self",
            date="2026-11-01", passages=[Passage(id="p001", text=text)],
        )
        case.add_claim(
            claim_id=f"{case_id}-claim",
            source_document_id="m1",
            source_version=1,
            source_passage_id="p001",
            provider_role="self_report",
            observation_setting="intake",
            record_time="2026-11-01",
            category="client_statement",
            topic="history",
            text=text,
        )
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(db_path))
    return build_client(create_app()), store


def test_overlapping_material_ids_stay_separate(seeded):
    client, _ = seeded
    a = client.get("/api/workspaces/case-a/materials").json()
    b = client.get("/api/workspaces/case-b/materials").json()
    assert [m["id"] for m in a] == ["m1"]
    assert [m["id"] for m in b] == ["m1"]
    assert a[0]["passages"][0]["text"] == "A intake paragraph."
    assert b[0]["passages"][0]["text"] == B_MARKER


def test_b_marker_never_leaks_into_a(seeded):
    client, _ = seeded
    for path in (
        "/api/workspaces/case-a/materials",
        "/api/workspaces/case-a/claims",
        "/api/workspaces/case-a/sections?template_id=intake-report",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert B_MARKER not in response.text


def test_claims_lists_are_isolated(seeded):
    client, _ = seeded
    a_claims = client.get("/api/workspaces/case-a/claims").json()
    b_claims = client.get("/api/workspaces/case-b/claims").json()
    assert [c["id"] for c in a_claims] == ["case-a-claim"]
    assert [c["id"] for c in b_claims] == ["case-b-claim"]


def test_accepting_b_claim_under_a_url_fails(seeded):
    """A suggestion built from B's material cannot be accepted through A."""
    client, _ = seeded
    suggestions = client.get(
        "/api/workspaces/case-b/materials/m1/suggestions",
        params={"provider_role": "self_report"},
    ).json()
    assert len(suggestions) == 1
    response = client.post("/api/workspaces/case-a/claims", json=suggestions[0])
    # A has its own material m1, so the id matches but the text does not.
    assert response.status_code == 400
    assert [c["id"] for c in client.get("/api/workspaces/case-a/claims").json()] == [
        "case-a-claim"
    ]


def test_egress_prepare_with_b_claim_ids_under_a_fails(seeded):
    client, _ = seeded
    response = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": "history",
            "claim_ids": ["case-b-claim"],
            "instructions": "write",
            "purpose": "section_generation",
        },
    )
    assert response.status_code == 400


def test_get_approve_send_b_request_via_a_url_is_404(seeded, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "synthetic")
    client, _ = seeded
    prepared = client.post(
        "/api/workspaces/case-b/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": "history",
            "claim_ids": ["case-b-claim"],
            "instructions": "write",
            "purpose": "section_generation",
        },
    )
    assert prepared.status_code == 200
    request_id = prepared.json()["request_id"]

    assert client.get(f"/api/workspaces/case-a/egress/{request_id}").status_code == 404
    approve = client.post(
        f"/api/workspaces/case-a/egress/{request_id}/approve",
        json={"content_hash": prepared.json()["content_hash"],
              "synthetic_auto_reason": "synthetic fixture"},
    )
    assert approve.status_code == 404
    assert client.post(f"/api/workspaces/case-a/egress/{request_id}/send").status_code == 404
    # The request itself is untouched and still sendable through B.
    assert client.get(f"/api/workspaces/case-b/egress/{request_id}").json()["status"] == "prepared"


def test_save_section_with_b_claim_ids_under_a_fails(seeded):
    client, _ = seeded
    response = client.put(
        "/api/workspaces/case-a/sections/history",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": "draft",
            "claim_ids": ["case-b-claim"],
            "status": "draft",
        },
    )
    assert response.status_code == 400
    states = client.get(
        "/api/workspaces/case-a/sections", params={"template_id": "intake-report"}
    ).json()
    assert all(s["status"] == "empty" for s in states)


def test_unknown_case_is_404_on_every_case_route(seeded):
    client, _ = seeded
    routes = [
        ("GET", "/api/workspaces/no-such/materials", None),
        ("GET", "/api/workspaces/no-such/claims", None),
        ("GET", "/api/workspaces/no-such/names", None),
        ("PUT", "/api/workspaces/no-such/names", {"names": []}),
        ("GET", "/api/workspaces/no-such/sections?template_id=intake-report", None),
        (
            "PUT",
            "/api/workspaces/no-such/sections/history",
            {
                "template_id": "intake-report",
                "template_version": 1,
                "text": "draft",
                "claim_ids": [],
                "status": "draft",
            },
        ),
        ("GET", "/api/workspaces/no-such/materials/m1/suggestions?provider_role=self_report", None),
        ("GET", "/api/workspaces/no-such/egress/req-1", None),
        (
            "POST",
            "/api/workspaces/no-such/egress/prepare",
            {
                "template_id": "intake-report",
                "template_version": 1,
                "section_id": "history",
                "claim_ids": [],
                "instructions": "write",
                "purpose": "section_generation",
            },
        ),
        (
            "POST",
            "/api/workspaces/no-such/egress/req-1/approve",
            {"content_hash": "0" * 64, "reviewer": "reviewer-1"},
        ),
        ("POST", "/api/workspaces/no-such/egress/req-1/send", None),
        (
            "POST",
            "/api/workspaces/no-such/materials/paste",
            {
                "material_id": "m1",
                "title": "t",
                "provider": "p",
                "date": "d",
                "text": "synthetic",
                "synthetic_confirmed": True,
            },
        ),
        ("POST", "/api/workspaces/no-such/sections/history/generate", None),
    ]
    for method, path, body in routes:
        kwargs = {"json": body} if body is not None else {}
        response = client.request(method, path, **kwargs)
        assert response.status_code == 404, f"{method} {path} -> {response.status_code}"
        assert response.json() == {"detail": "case not found"}, f"{method} {path}"


@pytest.mark.parametrize(
    "hostile",
    ["../x", "A' OR '1'='1", "%", "_", "a'b", "case--", "x; DROP TABLE cases;--", "案"],
)
def test_hostile_case_ids_rejected_on_routes(seeded, hostile):
    client, store = seeded
    # URL-encode so the id reaches the handler as one path segment.
    from urllib.parse import quote

    encoded = quote(hostile, safe="")
    response = client.get(f"/api/workspaces/{encoded}/materials")
    assert response.status_code in (400, 404), (hostile, response.status_code)
    # Wildcard-shaped ids must not pattern-match real cases.
    assert client.get("/api/workspaces/%25/materials").status_code in (400, 404)
    # And the store itself refuses them before any SQL runs.
    with pytest.raises((ValueError, UnknownCaseError)):
        store.case(hostile)


def test_store_level_isolation(seeded):
    _, store = seeded
    case_a = store.case("case-a")
    case_b = store.case("case-b")
    assert case_a.get_material("m1").passages[0].text == "A intake paragraph."
    assert case_b.get_material("m1").passages[0].text == B_MARKER
    with pytest.raises(KeyError):
        case_a.get_claim("case-b-claim")
    with pytest.raises(KeyError):
        case_b.get_claim("case-a-claim")


def test_r3_ac1_similar_materials_never_leak_b_content(tmp_path, monkeypatch):
    """PRD R3-AC1: with near-identical materials in A and B, case A's evidence
    list, saved section and outgoing model request must contain A's text and
    never the marker string that only exists in case B."""
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", "synthetic")
    client = build_client(create_app())

    a_text = "Synthetic intake note: sleep improved after the schedule change."
    b_text = "Synthetic intake note: sleep improved after the schedule change. " + B_MARKER
    for case_id, text in (("case-a", a_text), ("case-b", b_text)):
        assert client.post("/api/workspaces", json={"case_id": case_id}).status_code == 201
        pasted = client.post(
            f"/api/workspaces/{case_id}/materials/paste",
            json={
                "material_id": "m1",
                "title": "Intake note",
                "provider": "synthetic",
                "date": "2026-11-20",
                "text": text,
                "synthetic_confirmed": True,
            },
        )
        assert pasted.status_code == 200

    suggestions = client.get(
        "/api/workspaces/case-a/materials/m1/suggestions",
        params={"provider_role": "self_report"},
    ).json()
    accepted = client.post("/api/workspaces/case-a/claims", json=suggestions[0])
    assert accepted.status_code == 200

    # 1. A's evidence (claims) list: A's text, never B's marker.
    claims = client.get("/api/workspaces/case-a/claims")
    assert a_text in claims.text
    assert B_MARKER not in claims.text

    # 2. A's saved section referencing the claim: A's text, never B's marker.
    saved = client.put(
        "/api/workspaces/case-a/sections/history",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": a_text,
            "claim_ids": [accepted.json()["id"]],
            "status": "draft",
        },
    )
    assert saved.status_code == 200
    sections = client.get(
        "/api/workspaces/case-a/sections", params={"template_id": "intake-report"}
    )
    assert a_text in sections.text
    assert B_MARKER not in sections.text

    # 3. A's frozen outgoing model request (preview): A's text, never B's marker.
    prepared = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": "history",
            "claim_ids": [accepted.json()["id"]],
            "instructions": "Write the history section.",
            "purpose": "section_generation",
        },
    )
    assert prepared.status_code == 200
    preview = prepared.json()["preview"]
    assert "sleep improved after the schedule change" in preview
    assert B_MARKER not in preview
    # And the persisted request stays clean when re-read.
    persisted = client.get(
        f"/api/workspaces/case-a/egress/{prepared.json()['request_id']}"
    )
    assert B_MARKER not in persisted.text


def test_r1_ac2_switching_cases_shows_only_current_case_data(tmp_path, monkeypatch):
    """PRD R1-AC2: after 'switching' between cases (querying each case's own
    routes), materials, claims and sections returned are exactly the current
    case's data."""
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    client = build_client(create_app())

    texts = {"case-a": "Alpha synthetic paragraph.", "case-b": "Beta synthetic paragraph."}
    for case_id, text in texts.items():
        assert client.post("/api/workspaces", json={"case_id": case_id}).status_code == 201
        pasted = client.post(
            f"/api/workspaces/{case_id}/materials/paste",
            json={
                "material_id": "m1",
                "title": "Intake",
                "provider": "synthetic",
                "date": "2026-11-20",
                "text": text,
                "synthetic_confirmed": True,
            },
        )
        assert pasted.status_code == 200
        suggestions = client.get(
            f"/api/workspaces/{case_id}/materials/m1/suggestions",
            params={"provider_role": "self_report"},
        ).json()
        assert client.post(f"/api/workspaces/{case_id}/claims", json=suggestions[0]).status_code == 200
        saved = client.put(
            f"/api/workspaces/{case_id}/sections/history",
            json={
                "template_id": "intake-report",
                "template_version": 1,
                "text": text,
                "claim_ids": [suggestions[0]["id"]],
                "status": "draft",
            },
        )
        assert saved.status_code == 200

    # "Switch" A -> B -> A; each view shows only that case's data.
    for case_id, own_text in texts.items():
        other_text = texts["case-b" if case_id == "case-a" else "case-a"]
        materials = client.get(f"/api/workspaces/{case_id}/materials")
        assert own_text in materials.text and other_text not in materials.text
        claims = client.get(f"/api/workspaces/{case_id}/claims")
        assert own_text in claims.text and other_text not in claims.text
        sections = client.get(
            f"/api/workspaces/{case_id}/sections", params={"template_id": "intake-report"}
        )
        assert own_text in sections.text and other_text not in sections.text
