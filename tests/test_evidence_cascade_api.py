"""PT-09 chunk 2 (R6 / GROK-39 / ADR 0018): cascade results at the HTTP layer.

PUT /evidence/{id} and PUT /evidence/{id}/dimension pass the store's
structured ``invalidation`` summary through unchanged: stable-sorted id
lists plus the exact toast string. Category changes, category resets that
change the effective category, and dimension changes cascade; role-only and
no-op PUTs return empty lists with the no-cascade toast. Prepared and
approved egress requests referencing the item are invalidated; sent and
unrelated requests are not.

Synthetic data only.
"""

from __future__ import annotations

import pytest

from psychtool.server.app import create_app
from psychtool.store.sqlite_store import SqliteStore
from tests.conftest import build_client

TEACHER_MD = "Teacher says he reads slowly in class.\n"
TEACHER_TEXT = "Teacher says he reads slowly in class."
WEATHER_MD = "The weather was cloudy that week.\n"
WEATHER_TEXT = "The weather was cloudy that week."

NO_CASCADE_TOAST = (
    "Your change was saved. Nothing else needed to be updated. "
    "Unsaved text was not changed."
)


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


@pytest.fixture
def case(db_path):
    return SqliteStore(db_path).case("case-a")


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


def _evidence_item(client, needle, case_id="case-a"):
    payload = client.get(f"/api/workspaces/{case_id}/evidence").json()
    return next(item for item in payload["items"] if needle in item["quote"])


def _add_verified_claim(case, claim_id, text, evidence_id):
    claim = case.add_claim(
        claim_id=claim_id,
        source_document_id="note",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-11-24",
        category="client_statement",
        topic="history",
        text=text,
        evidence_ids=[evidence_id],
    )
    case.mark_claim_status(claim_id, "verified")
    return claim


def _save_approved_section(case, section_id, text, claim_ids):
    return case.save_section(
        template_id="intake-report",
        template_version=1,
        section_id=section_id,
        text=text,
        claim_ids=claim_ids,
        status="approved",
        review_gate="standard",
        reviewer="Dr. Synthetic",
        updated_at="2026-11-25T00:00:00+00:00",
    )


def _prepare_egress(client, claim_ids, section_id="history"):
    response = client.post(
        "/api/workspaces/case-a/egress/prepare",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "section_id": section_id,
            "claim_ids": claim_ids,
            "instructions": "Write the history section.",
            "purpose": "section_generation",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- category change cascades over HTTP (R6-AC1) ---------------------------------


def test_put_category_change_returns_invalidation_payload(client, case, db_path):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    item = _evidence_item(client, "reads slowly")
    ev = item["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    _save_approved_section(case, "history", "Saved section text.", ["c1"])
    prepared = _prepare_egress(client, ["c1"])

    response = client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"category": "other"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Existing evidence fields are unchanged in shape; the item shows the new
    # category and the structured invalidation rides along.
    assert body["id"] == ev
    assert body["category"] == "other"
    assert body["category_set_by"] == "clinician"
    assert body["invalidation"]["claims"] == ["c1"]
    assert body["invalidation"]["sections"] == ["history"]
    assert body["invalidation"]["egress"] == [prepared["request_id"]]
    assert body["invalidation"]["toast"] == (
        "Your change was saved. "
        "1 citing statement is no longer marked verified. "
        "1 section was returned to Needs review. "
        "1 prepared request was invalidated and must be prepared again. "
        "Unsaved text was not changed."
    )
    # The cascade is real, not just reported: claim pending, section back to
    # needs_review with the SAME text, request invalidated.
    assert case.get_claim("c1").verification_status == "pending"
    section = case.get_section("intake-report", "history")
    assert section.status == "needs_review"
    assert section.text == "Saved section text."
    status = client.get(
        f"/api/workspaces/case-a/egress/{prepared['request_id']}"
    ).json()["status"]
    assert status == "invalidated"


def test_put_category_change_toast_plural_counts(client, case):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    ev = _evidence_item(client, "reads slowly")["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    _add_verified_claim(case, "c2", TEACHER_TEXT + " (second)", ev)
    _save_approved_section(case, "history", "Saved text one.", ["c1"])
    _save_approved_section(case, "client_details", "Saved text two.", ["c2"])
    _prepare_egress(client, ["c1"], section_id="history")
    _prepare_egress(client, ["c1"], section_id="history")

    body = client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"category": "other"}
    ).json()

    invalidation = body["invalidation"]
    assert invalidation["claims"] == ["c1", "c2"]
    assert invalidation["sections"] == ["client_details", "history"]
    assert len(invalidation["egress"]) == 2
    assert invalidation["toast"] == (
        "Your change was saved. "
        "2 citing statements are no longer marked verified. "
        "2 sections were returned to Needs review. "
        "2 prepared requests were invalidated and must be prepared again. "
        "Unsaved text was not changed."
    )


# -- role-only and no-op PUTs: 200, empty lists, no-cascade toast -----------------


def test_put_role_only_returns_no_cascade_toast(client, case):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    ev = _evidence_item(client, "reads slowly")["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    _save_approved_section(case, "history", "Saved section text.", ["c1"])

    response = client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"role": "caregiver"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "caregiver"
    assert body["invalidation"] == {
        "claims": [],
        "sections": [],
        "egress": [],
        "toast": NO_CASCADE_TOAST,
    }
    assert case.get_claim("c1").verification_status == "verified"
    assert case.get_section("intake-report", "history").status == "approved"


def test_put_noop_category_returns_no_cascade_toast(client, case):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    item = _evidence_item(client, "reads slowly")
    ev = item["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    # Writing the category the item already effectively shows.
    body = client.put(
        f"/api/workspaces/case-a/evidence/{ev}",
        json={"category": item["suggested_category"]},
    ).json()
    assert body["invalidation"]["claims"] == []
    assert body["invalidation"]["toast"] == NO_CASCADE_TOAST
    assert case.get_claim("c1").verification_status == "verified"


# -- category reset that changes the effective category cascades ------------------


def test_put_category_reset_cascades_when_effective_category_changes(client, case):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    item = _evidence_item(client, "reads slowly")
    ev = item["id"]
    suggested = item["suggested_category"]
    other = "other" if suggested != "other" else "daily_living"
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    _save_approved_section(case, "history", "Saved section text.", ["c1"])

    # Her correction cascades once.
    first = client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"category": other}
    ).json()
    assert first["invalidation"]["claims"] == ["c1"]
    # Restore a clean verified/approved state under her category.
    case.mark_claim_status("c1", "verified")
    _save_approved_section(case, "history", "Saved section text.", ["c1"])

    # Reset (explicit null) returns the display to the different suggestion:
    # that IS an effective change, so the cascade runs again.
    response = client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"category": None}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"] == suggested  # effective falls back to suggestion
    assert body["category_set_by"] == "suggestion"
    assert body["invalidation"]["claims"] == ["c1"]
    assert body["invalidation"]["sections"] == ["history"]
    assert case.get_claim("c1").verification_status == "pending"
    section = case.get_section("intake-report", "history")
    assert section.status == "needs_review"
    assert section.text == "Saved section text."


def test_put_category_reset_without_effective_change_is_noop(client, case):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    ev = _evidence_item(client, "reads slowly")["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    body = client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"category": None}
    ).json()
    assert body["invalidation"] == {
        "claims": [],
        "sections": [],
        "egress": [],
        "toast": NO_CASCADE_TOAST,
    }
    assert case.get_claim("c1").verification_status == "verified"


# -- dimension change cascades over HTTP (R7-AC4) ---------------------------------


def _upload_dims_list(client):
    response = client.post(
        "/api/workspaces/case-a/materials",
        data={"material_id": "dims-list", "title": "Working list",
              "provider": "synthetic author", "date": "2026-11-24",
              "kind": "dims"},
        files={"file": ("dims-list.md",
                        b"Dimension 1: Attention\nDimension 2: Sleep and routine",
                        "application/octet-stream")},
    )
    assert response.status_code == 200, response.text


def test_put_dimension_change_returns_invalidation_payload(client, case):
    _upload_dims_list(client)
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    ev = _evidence_item(client, "reads slowly")["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    _save_approved_section(case, "history", "Saved section text.", ["c1"])
    prepared = _prepare_egress(client, ["c1"])
    view = client.get("/api/workspaces/case-a/dimensions").json()
    target = next(d for d in view["dimensions"] if d["name"] == "Sleep and routine")

    response = client.put(
        f"/api/workspaces/case-a/evidence/{ev}/dimension",
        json={"dimension_id": target["id"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dimension_id"] == target["id"]
    assert body["dimension_name"] == "Sleep and routine"
    assert body["dim_state"] == "confirmed"
    assert body["invalidation"]["claims"] == ["c1"]
    assert body["invalidation"]["sections"] == ["history"]
    assert body["invalidation"]["egress"] == [prepared["request_id"]]
    assert body["invalidation"]["toast"] == (
        "Your change was saved. "
        "1 citing statement is no longer marked verified. "
        "1 section was returned to Needs review. "
        "1 prepared request was invalidated and must be prepared again. "
        "Unsaved text was not changed."
    )
    assert case.get_claim("c1").verification_status == "pending"
    assert case.get_section("intake-report", "history").status == "needs_review"


def test_put_dimension_noop_returns_no_cascade_toast(client, case):
    _upload_dims_list(client)
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    ev = _evidence_item(client, "reads slowly")["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    view = client.get("/api/workspaces/case-a/dimensions").json()
    target = next(d for d in view["dimensions"] if d["name"] == "Sleep and routine")
    url = f"/api/workspaces/case-a/evidence/{ev}/dimension"
    first = client.put(url, json={"dimension_id": target["id"]}).json()
    assert first["invalidation"]["claims"] == ["c1"]
    case.mark_claim_status("c1", "verified")
    # Same dimension again: effective id unchanged, no cascade.
    second = client.put(url, json={"dimension_id": target["id"]}).json()
    assert second["invalidation"] == {
        "claims": [],
        "sections": [],
        "egress": [],
        "toast": NO_CASCADE_TOAST,
    }
    assert case.get_claim("c1").verification_status == "verified"


# -- egress three-state behavior at the HTTP layer ---------------------------------


def test_put_invalidates_prepared_but_not_sent_or_unrelated(client, case):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    _upload(client, "case-a", "weather", WEATHER_MD, "Weather note")
    ev = _evidence_item(client, "reads slowly")["id"]
    weather_ev = _evidence_item(client, "weather")["id"]
    _add_verified_claim(case, "c1", TEACHER_TEXT, ev)
    weather_claim = case.add_claim(
        claim_id="c2",
        source_document_id="weather",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-11-24",
        category="client_statement",
        topic="history",
        text=WEATHER_TEXT,
        evidence_ids=[weather_ev],
    )
    assert weather_claim.id == "c2"
    prepared = _prepare_egress(client, ["c1"])
    unrelated = _prepare_egress(client, ["c2"], section_id="client_details")
    # A second prepared request that we send through the fake transport.
    to_send = _prepare_egress(client, ["c1"])
    approve = client.post(
        f"/api/workspaces/case-a/egress/{to_send['request_id']}/approve",
        json={"reviewer": "Dr. Synthetic", "content_hash": to_send["content_hash"]},
    )
    assert approve.status_code == 200, approve.text
    sent = client.post(f"/api/workspaces/case-a/egress/{to_send['request_id']}/send")
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"

    body = client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"category": "other"}
    ).json()

    assert body["invalidation"]["egress"] == [prepared["request_id"]]
    statuses = {
        rid: client.get(f"/api/workspaces/case-a/egress/{rid}").json()["status"]
        for rid in (
            prepared["request_id"],
            unrelated["request_id"],
            to_send["request_id"],
        )
    }
    assert statuses[prepared["request_id"]] == "invalidated"
    assert statuses[unrelated["request_id"]] == "prepared"
    assert statuses[to_send["request_id"]] == "sent"


# -- 400/404 paths unchanged --------------------------------------------------------


def test_put_evidence_error_paths_unchanged(client):
    _upload(client, "case-a", "note", TEACHER_MD, "School note")
    ev = _evidence_item(client, "reads slowly")["id"]
    assert client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={}
    ).status_code == 400
    assert client.put(
        f"/api/workspaces/case-a/evidence/{ev}", json={"category": "nope"}
    ).status_code == 400
    assert client.put(
        "/api/workspaces/case-a/evidence/ev_missing", json={"category": "other"}
    ).status_code == 404
    assert client.put(
        f"/api/workspaces/case-a/evidence/{ev}/dimension", json={}
    ).status_code == 400
    assert client.put(
        "/api/workspaces/case-a/evidence/ev_missing/dimension",
        json={"action": "none"},
    ).status_code == 404
