"""R4 (PT-06 / ADR 0014): evidence API — verbatim quotes, spans, isolation.

- R4-AC1: every evidence item carries the verbatim quote plus its material,
  version and paragraph / character range (quote == passage.text[start:end]).
- R4-AC3: conflicting accounts in different materials are both kept.
- Only the latest material version is used; one case never sees another
  case's text; the route writes nothing (claims/sections/egress/audit rows
  unchanged); unknown case -> fixed 404.
"""

from __future__ import annotations

import sqlite3

import pytest

from psychtool.server.app import create_app
from tests.conftest import build_client

CAREGIVER_MD = (
    "Mother says he sleeps about 8 hours a night and keeps a regular "
    "routine.\n\nHe walks to school with a neighbour.\n"
)
SELF_MD = "I often stay on my phone until about 1 a.m. before falling asleep.\n"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "psychtool.db"
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db_path):
    api = build_client(create_app())
    assert api.post("/api/workspaces", json={"case_id": "case-a"}).status_code == 201
    api.post("/api/workspaces/case-a/synthetic-confirmation")
    return api


def _upload(client, case_id, material_id, text, title):
    response = client.post(
        f"/api/workspaces/{case_id}/materials",
        data={"material_id": material_id, "title": title,
              "provider": "synthetic author", "date": "2026-11-24"},
        files={"file": (f"{material_id}.md", text.encode(),
                        "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed(client, case_id="case-a"):
    _upload(client, case_id, "caregiver", CAREGIVER_MD, "Caregiver note")
    _upload(client, case_id, "self", SELF_MD, "Self report")


def _evidence(client, case_id="case-a"):
    response = client.get(f"/api/workspaces/{case_id}/evidence")
    assert response.status_code == 200, response.text
    return response.json()


def _table_counts(db_path):
    raw = sqlite3.connect(db_path)
    counts = {
        table: raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("claims", "sections", "egress_requests", "audit_log")
    }
    raw.close()
    return counts


def _passage_text(client, case_id, material_id, passage_id):
    materials = client.get(f"/api/workspaces/{case_id}/materials").json()
    material = next(m for m in materials if m["id"] == material_id)
    return next(p["text"] for p in material["passages"] if p["id"] == passage_id)


# -- R4-AC1 -------------------------------------------------------------------


def test_r4_ac1_evidence_items_have_quote_and_range(client):
    _seed(client)
    payload = _evidence(client)
    assert payload["extractor"] == "rule"
    items = payload["items"]
    assert len(items) == 3  # two caregiver sentences + one self-report

    material_titles = {item["material_id"]: item["material_title"] for item in items}
    assert material_titles == {"caregiver": "Caregiver note", "self": "Self report"}

    for item in items:
        for key in ("id", "quote", "material_id", "material_title",
                    "material_version", "passage_id", "paragraph", "start", "end"):
            assert key in item, key
        assert item["material_version"] == 1
        text = _passage_text(client, "case-a", item["material_id"], item["passage_id"])
        # The quote is verbatim equal to the stored source slice (code points).
        assert text[item["start"] : item["end"]] == item["quote"]

    caregiver_items = [i for i in items if i["material_id"] == "caregiver"]
    assert len(caregiver_items) == 2
    by_quote = {i["quote"]: i for i in caregiver_items}
    routine = by_quote["Mother says he sleeps about 8 hours a night and keeps "
                       "a regular routine"]
    assert routine["material_title"] == "Caregiver note"
    assert routine["paragraph"] == 1
    assert routine["start"] == 0
    walks = by_quote["He walks to school with a neighbour"]
    assert walks["paragraph"] == 2


def test_r4_ac1_only_latest_version_used(client):
    _upload(client, "case-a", "caregiver",
            "First version says he sleeps about 8 hours nightly.\n", "Old note")
    _upload(client, "case-a", "caregiver", CAREGIVER_MD, "Caregiver note")
    payload = _evidence(client)
    caregiver_items = [i for i in payload["items"] if i["material_id"] == "caregiver"]
    assert len(caregiver_items) == 2
    assert all(i["material_version"] == 2 for i in caregiver_items)
    assert all("First version" not in i["quote"] for i in caregiver_items)


def test_evidence_case_isolation(client):
    _seed(client, "case-a")
    assert client.post("/api/workspaces", json={"case_id": "case-b"}).status_code == 201
    client.post("/api/workspaces/case-b/synthetic-confirmation")
    _upload(client, "case-b", "other",
            "Case B has its own unique sentence about a paper planner.\n", "B note")
    payload = _evidence(client, "case-a")
    all_quotes = "\n".join(item["quote"] for item in payload["items"])
    assert "paper planner" not in all_quotes
    assert {item["material_id"] for item in payload["items"]} == {"caregiver", "self"}


def test_evidence_route_writes_nothing(client, db_path):
    _seed(client)
    before = _table_counts(db_path)
    payload = _evidence(client)
    assert payload["items"]
    assert _table_counts(db_path) == before


def test_evidence_unknown_case_404(client):
    response = client.get("/api/workspaces/no-such-case/evidence")
    assert response.status_code == 404
    assert response.json() == {"detail": "case not found"}


def test_evidence_empty_case_has_no_items(client):
    payload = _evidence(client)
    assert payload == {
        "extractor": "rule",
        "rules_version": "rule-1",
        "items": [],
        "needs_extraction": False,
    }


# -- R4-AC3 -------------------------------------------------------------------


def test_r4_ac3_conflicting_accounts_both_kept(client):
    _seed(client)
    payload = _evidence(client)
    by_material: dict[str, list[str]] = {}
    for item in payload["items"]:
        by_material.setdefault(item["material_id"], []).append(item["quote"])
    assert any("8 hours" in quote for quote in by_material["caregiver"])
    assert any("1 a.m." in quote for quote in by_material["self"])
    # Each item keeps its own visible source (material + paragraph + range).
    caregiver = next(i for i in payload["items"] if i["material_id"] == "caregiver")
    self_item = next(i for i in payload["items"] if i["material_id"] == "self")
    assert caregiver["passage_id"] != self_item["passage_id"] or \
        caregiver["material_id"] != self_item["material_id"]
    for item in (caregiver, self_item):
        text = _passage_text(client, "case-a", item["material_id"], item["passage_id"])
        assert text[item["start"] : item["end"]] == item["quote"]
