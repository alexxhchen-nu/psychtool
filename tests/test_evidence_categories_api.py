"""R5 (PT-07 / GROK-37 / ADR 0015): evidence API — categories, reasons, roles.

- R5-AC1: every categorized item carries a category name and a one-sentence
  reason (<= 140 chars) that quotes a verbatim substring of the item's quote.
- R5-AC2: undecidable items are ``uncategorized`` with the fixed reason —
  never a guess, never ``other``.
- Upload persists evidence automatically; GET is read-only; PUT records her
  choice (allowlisted keys, fixed 400/404 bodies, audit rows without text);
  POST refresh is idempotent; one case never sees another case's rows.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

from psychtool.core.categorize import UNCATEGORIZED_REASON
from psychtool.server.app import create_app
from tests.conftest import build_client

TEACHER_MD = "Teacher says he reads slowly in class.\n\nThe weather was cloudy that week.\n"
# "Per the medical record," survives the identifier redactor (unlike
# "medical record lists/shows", which matches the MRN pattern).
MEDICAL_MD = "Per the medical record, he had a head injury in 2024.\n"


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
    _upload(client, case_id, "school", TEACHER_MD, "School note")
    _upload(client, case_id, "medical", MEDICAL_MD, "Medical note")


def _evidence(client, case_id="case-a"):
    response = client.get(f"/api/workspaces/{case_id}/evidence")
    assert response.status_code == 200, response.text
    return response.json()


def _item(payload, needle):
    return next(item for item in payload["items"] if needle in item["quote"])


def _table_counts(db_path):
    raw = sqlite3.connect(db_path)
    counts = {
        table: raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("claims", "sections", "egress_requests", "audit_log", "evidence")
    }
    raw.close()
    return counts


def _audit_rows(db_path, action):
    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    rows = raw.execute(
        "SELECT * FROM audit_log WHERE action = ?", (action,)
    ).fetchall()
    raw.close()
    return [dict(row) for row in rows]


# -- upload -> persisted automatically -----------------------------------------


def test_upload_persists_evidence_automatically(client):
    _seed(client)
    payload = _evidence(client)
    assert payload["needs_extraction"] is False
    assert len(payload["items"]) == 3
    assert all(item["id"].startswith("ev_") for item in payload["items"])


def test_paste_persists_evidence_automatically(client):
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "pasted",
            "title": "Pasted note",
            "provider": "synthetic author",
            "date": "2026-11-24",
            "text": "Mother says he sleeps about 8 hours a night.",
            "synthetic_confirmed": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = _evidence(client)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["material_id"] == "pasted"


# -- R5-AC1 ---------------------------------------------------------------------


def test_r5_ac1_item_shows_category_and_verbatim_reason(client):
    _seed(client)
    payload = _evidence(client)
    teacher = _item(payload, "Teacher")
    assert teacher["category"] == "development_school"
    assert teacher["category_label"] == "Development & school"
    assert teacher["category_set_by"] == "suggestion"
    # The reason is one sentence, at most two lines, and quotes a verbatim
    # substring of the item's quote — never "based on context".
    assert len(teacher["category_reason"]) <= 140
    match = re.search(r"“(.+?)”", teacher["category_reason"])
    assert match, teacher["category_reason"]
    assert match.group(1) in teacher["quote"]
    # Role is recorded separately from category.
    assert teacher["role"] == "school"
    assert teacher["role_label"] == "School"
    assert teacher["role_set_by"] == "suggestion"
    role_match = re.search(r"“(.+?)”", teacher["role_reason"])
    assert role_match and role_match.group(1) in teacher["quote"]


def test_r5_ac1_every_item_has_reason_pointing_at_source(client):
    _seed(client)
    payload = _evidence(client)
    for item in payload["items"]:
        assert item["category"] and item["category_label"]
        assert item["role"] and item["role_label"]
        assert len(item["category_reason"]) <= 140
        assert len(item["role_reason"]) <= 140
        if item["category"] != "uncategorized":
            match = re.search(r"“(.+?)”", item["category_reason"])
            assert match and match.group(1) in item["quote"], item


def test_r5_ac1_role_recorded_separately_from_category(client):
    _seed(client)
    payload = _evidence(client)
    medical = _item(payload, "medical record")
    # Category says medical history; role says medical record — independent.
    assert medical["category"] == "medical_history"
    assert medical["role"] == "medical_record"


# -- R5-AC2 ---------------------------------------------------------------------


def test_r5_ac2_undecidable_item_is_uncategorized(client):
    _seed(client)
    payload = _evidence(client)
    weather = _item(payload, "weather")
    assert weather["category"] == "uncategorized"
    assert weather["category_label"] == "Uncategorized"
    assert weather["category_reason"] == UNCATEGORIZED_REASON
    assert weather["category"] != "other"
    # No role keyword either -> to_confirm with the fixed reason.
    assert weather["role"] == "to_confirm"
    assert weather["role_reason"] == (
        "Nothing in the text says who provided it; please confirm."
    )


# -- GET is read-only -------------------------------------------------------------


def test_get_evidence_writes_nothing(client, db_path):
    _seed(client)
    before = _table_counts(db_path)
    payload = _evidence(client)
    assert payload["items"]
    assert _table_counts(db_path) == before


def test_evidence_case_isolation(client):
    _seed(client, "case-a")
    assert client.post("/api/workspaces", json={"case_id": "case-b"}).status_code == 201
    client.post("/api/workspaces/case-b/synthetic-confirmation")
    _upload(client, "case-b", "other", "Case B sentence about the school bus.\n", "B note")
    payload = _evidence(client, "case-a")
    assert all("school bus" not in item["quote"] for item in payload["items"])
    assert {item["material_id"] for item in payload["items"]} == {"school", "medical"}


def test_evidence_unknown_case_404(client):
    response = client.get("/api/workspaces/no-such-case/evidence")
    assert response.status_code == 404
    assert response.json() == {"detail": "case not found"}


# -- PUT corrections ---------------------------------------------------------------


def test_put_category_records_choice_and_audits_without_text(client, db_path):
    _seed(client)
    weather = _item(_evidence(client), "weather")
    response = client.put(
        f"/api/workspaces/case-a/evidence/{weather['id']}",
        json={"category": "other"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"] == "other"
    assert body["category_label"] == "Other"
    assert body["category_set_by"] == "clinician"
    # The effective reason is about HER choice; the rule's reason moved to
    # the suggestion fields (never shown next to her chip).
    assert body["category_reason"] == "You chose this category."
    assert body["suggested_category_reason"] == UNCATEGORIZED_REASON
    audits = _audit_rows(db_path, "evidence.categorize")
    assert len(audits) == 1
    assert audits[0]["object_type"] == "evidence"
    assert audits[0]["object_id"] == weather["id"]
    assert audits[0]["content_hash"] is None  # ids only, never text
    # The choice is persisted: a fresh GET shows it.
    again = _item(_evidence(client), "weather")
    assert again["category"] == "other"
    assert again["category_set_by"] == "clinician"


def test_put_role_records_choice(client, db_path):
    _seed(client)
    weather = _item(_evidence(client), "weather")
    response = client.put(
        f"/api/workspaces/case-a/evidence/{weather['id']}",
        json={"role": "caregiver"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "caregiver"
    assert response.json()["role_set_by"] == "clinician"
    audits = _audit_rows(db_path, "evidence.set_role")
    assert len(audits) == 1
    assert audits[0]["content_hash"] is None


def test_put_records_choice_and_shows_choice_reason(client):
    """After PUT the reason is about HER choice; the rule's keyword reason
    stays available on the suggested_* fields (never next to her chip)."""
    _seed(client)
    weather = _item(_evidence(client), "weather")
    response = client.put(
        f"/api/workspaces/case-a/evidence/{weather['id']}",
        json={"category": "other", "role": "caregiver"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category_reason"] == "You chose this category."
    assert body["role_reason"] == "You chose this source role."
    assert body["suggested_category"] == "uncategorized"
    assert body["suggested_category_reason"] == UNCATEGORIZED_REASON
    assert body["suggested_role"] == "to_confirm"
    # The GET list applies the same rule.
    again = _item(_evidence(client), "weather")
    assert again["category_reason"] == "You chose this category."
    assert again["role_reason"] == "You chose this source role."
    assert again["suggested_category_reason"] == UNCATEGORIZED_REASON
    assert again["category_set_by"] == "clinician"


def test_put_null_resets_to_suggestion(client):
    _seed(client)
    weather = _item(_evidence(client), "weather")
    client.put(f"/api/workspaces/case-a/evidence/{weather['id']}",
               json={"category": "other"})
    response = client.put(
        f"/api/workspaces/case-a/evidence/{weather['id']}",
        json={"category": None},
    )
    assert response.status_code == 200
    assert response.json()["category"] == "uncategorized"
    assert response.json()["category_set_by"] == "suggestion"
    # After the reset the rule's reason comes back.
    assert response.json()["category_reason"] == UNCATEGORIZED_REASON
    again = _item(_evidence(client), "weather")
    assert again["category_reason"] == UNCATEGORIZED_REASON


def test_put_rejects_non_allowlisted_keys(client):
    _seed(client)
    weather = _item(_evidence(client), "weather")
    response = client.put(
        f"/api/workspaces/case-a/evidence/{weather['id']}",
        json={"category": "diagnosis"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid evidence choice"}
    response = client.put(
        f"/api/workspaces/case-a/evidence/{weather['id']}",
        json={"role": "parent"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid evidence choice"}


def test_put_unknown_evidence_404(client):
    _seed(client)
    response = client.put(
        "/api/workspaces/case-a/evidence/ev_doesnotexist00",
        json={"category": "other"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "evidence not found"}


def test_put_empty_body_400(client):
    _seed(client)
    weather = _item(_evidence(client), "weather")
    response = client.put(
        f"/api/workspaces/case-a/evidence/{weather['id']}", json={}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid evidence choice"}


# -- refresh route ------------------------------------------------------------------


def test_refresh_route_is_idempotent(client, db_path):
    _seed(client)
    first = client.post("/api/workspaces/case-a/evidence/refresh")
    assert first.status_code == 200, first.text
    audits_before = len(_audit_rows(db_path, "evidence.extract"))
    second = client.post("/api/workspaces/case-a/evidence/refresh")
    assert second.status_code == 200
    assert len(_audit_rows(db_path, "evidence.extract")) == audits_before
    assert second.json()["needs_extraction"] is False


def test_refresh_unknown_case_404(client):
    response = client.post("/api/workspaces/no-such-case/evidence/refresh")
    assert response.status_code == 404
    assert response.json() == {"detail": "case not found"}


def test_correction_survives_refresh(client):
    """The API-level Alex test: her category stays put across a refresh."""
    _seed(client)
    weather = _item(_evidence(client), "weather")
    client.put(f"/api/workspaces/case-a/evidence/{weather['id']}",
               json={"category": "other"})
    client.post("/api/workspaces/case-a/evidence/refresh")
    again = _item(_evidence(client), "weather")
    assert again["id"] == weather["id"]  # stable id
    assert again["category"] == "other"
    assert again["category_set_by"] == "clinician"
