"""R7 (PT-08 / GROK-38 / ADR 0016): dimension mapping API tests.

- R7-AC1: dimension names come only from her uploaded content.
- R7-AC2: no uploaded list -> no dimension from built-in knowledge.
- R7-AC3: mapped item shows name, <=140-char reason quoting visible text,
  and the dimension carries a clickable source range (passage/span).
- R7-AC4: she changes the dimension in one step (PUT); no re-upload.
  Invalidating citing sentences/sections is PT-09 — NOT here.
- R7-AC5: unsure mapping -> "Needs review"; never a guessed dimension.
- R7-AC6: nowhere a diagnosis-style phrase; every view shows the disclaimer.
- R7-AC7: mapping data never enters sections, drafts or egress payloads.
- R7-AC8: no criteria text / criterion-number citations without uploaded DSM.
- R7-AC9: a mapping cites only her uploaded range, labelled with its source.
- GET is read-only; 409 second list; case isolation; choice actions.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

from psychtool.core.dimensions import (
    DIAGNOSIS_PHRASES,
    NOT_DIAGNOSIS,
    find_blocked_citation,
)
from psychtool.server.app import create_app
from tests.conftest import build_client

PROTOTYPE_LIST = (
    "This is a clinician-made working list of the working areas we track "
    "for this practice, not any official criteria or diagnostic text.\n"
    "Dimension 1: Attention\n"
    "Dimension 2: Reading and decoding\n"
    "Dimension 3: Sleep and routine\n"
    "Dimension 4: Social interaction\n"
    "Dimension 5: Mood and emotion\n"
    "Dimension 6: Memory and processing speed"
)

NOTE_MD = (
    "He is distractible and cannot focus during homework.\n\n"
    "He reads slowly and mixes up words in reading class.\n\n"
    "He rides his bike after school every day."
)

CRITERION_NUMBERS = ("Criterion A1", "A.1", "F90.0", "314.01", "299.00")


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


def _upload(client, case_id, material_id, text, title, kind="case"):
    response = client.post(
        f"/api/workspaces/{case_id}/materials",
        data={"material_id": material_id, "title": title,
              "provider": "synthetic author", "date": "2026-11-24",
              "kind": kind},
        files={"file": (f"{material_id}.md", text.encode(),
                        "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_list(client, case_id="case-a", text=PROTOTYPE_LIST):
    return _upload(client, case_id, "dims-list", text, "Working list",
                   kind="dims")


def _seed(client, case_id="case-a"):
    _upload(client, case_id, "note", NOTE_MD, "Caregiver note")


def _dimensions(client, case_id="case-a"):
    response = client.get(f"/api/workspaces/{case_id}/dimensions")
    assert response.status_code == 200, response.text
    return response.json()


def _audit_count(db_path):
    raw = sqlite3.connect(db_path)
    count = raw.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    raw.close()
    return count


# -- R7-AC1 --------------------------------------------------------------------


def test_r7_ac1_names_come_only_from_her_upload(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    assert view["has_list"] is True
    names = [d["name"] for d in view["dimensions"]]
    assert names == [
        "Attention",
        "Reading and decoding",
        "Sleep and routine",
        "Social interaction",
        "Mood and emotion",
        "Memory and processing speed",
    ]
    # The intro sentence is not a dimension and every name is a substring of
    # her uploaded text (nothing invented, nothing built in).
    for dim in view["dimensions"]:
        assert dim["quote_text_of_passage_span"] == dim["name"]


def test_r7_ac1_custom_list_replaces_names_entirely(client):
    _seed(client)
    _upload_list(client, text="Dimension 1: Bicycle riding\nDimension 2: Cooking")
    view = _dimensions(client)
    assert [d["name"] for d in view["dimensions"]] == ["Bicycle riding", "Cooking"]
    # "Attention" from the prototype list must not leak in anywhere.
    assert all(item["dimension_name"] != "Attention" for item in view["items"])


# -- R7-AC2 --------------------------------------------------------------------


def test_r7_ac2_no_list_means_no_dimension(client):
    _seed(client)
    view = _dimensions(client)
    assert view["has_list"] is False
    assert view["list"] is None
    assert view["dimensions"] == []
    for item in view["items"]:
        assert item["dimension_id"] is None
        assert item["dim_state"] in ("none", "needs_review")
        assert "No dimension list" in item["dim_reason"]


# -- R7-AC3 --------------------------------------------------------------------


def test_r7_ac3_mapped_item_reason_and_source_range(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    mapped = next(
        item for item in view["items"] if item["dimension_name"] == "Attention"
    )
    assert mapped["dim_state"] == "needs_review"
    assert len(mapped["dim_reason"]) <= 140
    # The reason quotes a verbatim substring of the item's visible text.
    quoted = re.findall(r"“([^”]+)”", mapped["dim_reason"])
    assert quoted and any(fragment in mapped["quote"] for fragment in quoted)
    # Clickable source range: the item's own span is present.
    assert mapped["passage_id"] and 0 <= mapped["start"] < mapped["end"]
    # The dimension's list-side source range points at the list passage.
    attention = next(d for d in view["dimensions"] if d["name"] == "Attention")
    assert attention["quote_text_of_passage_span"] == "Attention"
    assert attention["paragraph"] == 2


# -- R7-AC4 --------------------------------------------------------------------


def test_r7_ac4_change_dimension_in_one_step(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    mapped = next(
        item for item in view["items"] if item["dimension_name"] == "Attention"
    )
    target = next(d for d in view["dimensions"] if d["name"] == "Sleep and routine")
    response = client.put(
        f"/api/workspaces/case-a/evidence/{mapped['id']}/dimension",
        json={"dimension_id": target["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dimension_name"] == "Sleep and routine"
    assert body["dim_state"] == "confirmed"
    assert body["dim_set_by"] == "clinician"
    # The change is persisted without any re-upload or new case.
    reread = _dimensions(client)
    changed = next(i for i in reread["items"] if i["id"] == mapped["id"])
    assert changed["dimension_name"] == "Sleep and routine"
    # NOTE (PT-09): citing sentences/sections are NOT invalidated here.


def test_r7_ac4_confirm_and_none_and_reset(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    mapped = next(
        item for item in view["items"] if item["dimension_name"] == "Attention"
    )
    url = f"/api/workspaces/case-a/evidence/{mapped['id']}/dimension"
    assert client.put(url, json={"action": "confirm"}).status_code == 200
    assert client.put(url, json={"action": "none"}).status_code == 200
    none_state = client.put(url, json={"action": "reset"}).json()
    assert none_state["dim_state"] == "needs_review"
    assert none_state["dim_set_by"] == "suggestion"


# -- R7-AC5 --------------------------------------------------------------------


def test_r7_ac5_unsure_mapping_is_needs_review_never_guessed(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    # "distractible" hits Attention once -> needs_review WITH the dimension.
    mapped = next(
        item for item in view["items"] if item["dimension_name"] == "Attention"
    )
    assert mapped["dim_state"] == "needs_review"
    # "reads slowly ... words in reading class" hits Reading AND (through
    # "words"? no) — check the ambiguous case with a crafted quote.
    _upload(client, "case-a", "mixed",
            "He reads slowly and sleeps badly at night.\n", "Mixed note")
    view = _dimensions(client)
    ambiguous = next(
        item for item in view["items"]
        if "reads slowly and sleeps" in item["quote"]
    )
    # Two dimensions hit -> no dimension assigned, visibly needs review.
    assert ambiguous["dim_state"] == "needs_review"
    assert ambiguous["dimension_id"] is None
    assert "cannot tell" in ambiguous["dim_reason"]
    # No item is ever auto-confirmed by the system.
    assert all(
        item["dim_state"] != "confirmed" or item["dim_set_by"] == "clinician"
        for item in view["items"]
    )


# -- R7-AC6 --------------------------------------------------------------------


def test_r7_ac6_no_diagnosis_language_and_disclaimer_everywhere(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    assert view["disclaimer"] == NOT_DIAGNOSIS
    texts = [view["disclaimer"]]
    texts += [d["name"] for d in view["dimensions"]]
    for item in view["items"]:
        texts.append(item["dim_reason"])
        if item["dimension_name"]:
            texts.append(item["dimension_name"])
    for text in texts:
        if text == NOT_DIAGNOSIS:
            continue  # the fixed required disclaimer contains "diagnosis is"
        lowered = text.casefold()
        for phrase in (
            "meets criteria",
            "consistent with a diagnosis of",
            "diagnosis is",
            "suggests a diagnosis",
            "diagnosed with",
            "criteria for",
        ):
            assert phrase not in lowered, f"{phrase!r} leaked into {text!r}"
    # The evidence list carries the same fields; also diagnosis-free.
    evidence = client.get("/api/workspaces/case-a/evidence").json()
    for item in evidence["items"]:
        assert find_blocked_citation(item["dim_reason"] or "") is None


def test_r7_ac6_blocked_list_line_is_held_back_not_a_dimension(client):
    _seed(client)
    _upload_list(client, text=(
        "Dimension 1: Attention\n"
        "Dimension 2: Meets criteria for ADHD\n"
        "Dimension 3: Sleep and routine"
    ))
    view = _dimensions(client)
    names = [d["name"] for d in view["dimensions"]]
    assert names == ["Attention", "Sleep and routine"]
    assert view["held_back"] == 1
    assert view["disclaimer"] == NOT_DIAGNOSIS


# -- R7-AC7 --------------------------------------------------------------------


def test_r7_ac7_mapping_never_enters_sections_drafts_or_egress(client, db_path):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    mapped = next(
        item for item in view["items"] if item["dimension_name"] == "Attention"
    )
    client.put(
        f"/api/workspaces/case-a/evidence/{mapped['id']}/dimension",
        json={"action": "confirm"},
    )
    client.put(
        f"/api/workspaces/case-a/evidence/{mapped['id']}/dimension",
        json={"dimension_id": _dimensions(client)["dimensions"][2]["id"]},
    )
    dimension_names = {d["name"] for d in view["dimensions"]}
    reasons = [item["dim_reason"] for item in view["items"]]

    # She writes a diagnosis/impression section by hand; the saved text must
    # not contain anything from the mapping.
    response = client.put(
        "/api/workspaces/case-a/sections/clinical_impressions",
        json={
            "template_id": "intake-report",
            "template_version": 1,
            "text": "My own clinical impression, written by hand.",
            "claim_ids": [],
            "status": "draft",
        },
    )
    assert response.status_code == 200, response.text
    raw = sqlite3.connect(db_path)
    section_text = raw.execute(
        "SELECT text FROM sections WHERE section_id = 'clinical_impressions'"
    ).fetchone()[0]
    for name in dimension_names:
        assert name not in section_text
    for reason in reasons:
        assert (reason or "") not in section_text
    # Guard at the persistence layer: no code path wrote dimension columns
    # into sections or egress payloads.
    section_columns = {
        row[1] for row in raw.execute("PRAGMA table_info(sections)")
    }
    egress_columns = {
        row[1] for row in raw.execute("PRAGMA table_info(egress_requests)")
    }
    assert not ({"dimension_id", "dim_reason", "dimension_name"} & section_columns)
    assert not ({"dimension_id", "dim_reason", "dimension_name"} & egress_columns)
    raw.close()


# -- R7-AC8 --------------------------------------------------------------------


def test_r7_ac8_no_criteria_citations_without_uploaded_dsm_text(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    reasons = [d["name"] for d in view["dimensions"]]
    reasons += [item["dim_reason"] for item in view["items"]]
    reasons += [item["dimension_name"] or "" for item in view["items"]]
    for text in reasons:
        assert find_blocked_citation(text or "") is None, text
        for token in CRITERION_NUMBERS:
            assert token not in (text or ""), f"{token} leaked into {text!r}"
    # And a hostile list line with a citation is held back, never surfaced.
    _upload_list(client, text=(
        "Dimension 1: Attention\n"
        "Dimension 2: F90.0 problems\n"
        "Dimension 3: Sleep and routine"
    ))
    view = _dimensions(client)
    assert view["held_back"] == 1
    assert all("F90.0" not in (item["dim_reason"] or "") for item in view["items"])


# -- R7-AC9 --------------------------------------------------------------------


def test_r7_ac9_mapping_cites_only_her_uploaded_range_with_source_label(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    assert view["list"] == {"material_id": "dims-list",
                            "title": "Working list", "version": 1}
    attention = next(d for d in view["dimensions"] if d["name"] == "Attention")
    # Only her uploaded range is shown: the span text equals the name and
    # nothing else is added (no criteria, no numbering, no extra words).
    assert attention["quote_text_of_passage_span"] == "Attention"
    assert attention["paragraph"] == 2
    # The label pieces the UI needs: list title, version, paragraph.
    assert view["list"]["title"] == "Working list"
    assert view["list"]["version"] == 1
    assert attention["paragraph"] >= 1
    for dim in view["dimensions"]:
        assert dim["quote_text_of_passage_span"] == dim["name"]


# -- route behaviour ------------------------------------------------------------


def test_dimensions_get_is_read_only(client, db_path):
    _seed(client)
    _upload_list(client)
    before = _audit_count(db_path)
    response = client.get("/api/workspaces/case-a/dimensions")
    assert response.status_code == 200
    assert _audit_count(db_path) == before  # GET wrote nothing


def test_dimensions_unknown_case_404(client):
    response = client.get("/api/workspaces/nope/dimensions")
    assert response.status_code == 404
    assert response.json() == {"detail": "case not found"}


def test_second_dims_upload_409_fixed_body(client):
    _upload_list(client)
    response = client.post(
        "/api/workspaces/case-a/materials",
        data={"material_id": "other-list", "title": "Other",
              "provider": "synthetic author", "date": "2026-11-24",
              "kind": "dims"},
        files={"file": ("other.md", b"Dimension 1: Sleep",
                        "application/octet-stream")},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "dimension list exists"}
    # Same material_id re-upload is a new version, not a 409.
    response = client.post(
        "/api/workspaces/case-a/materials",
        data={"material_id": "dims-list", "title": "Working list",
              "provider": "synthetic author", "date": "2026-11-24",
              "kind": "dims"},
        files={"file": ("dims-list.md",
                        (PROTOTYPE_LIST + "\nDimension 7: Processing speed").encode(),
                        "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    view = _dimensions(client)
    assert view["list"]["version"] == 2
    assert len(view["dimensions"]) == 7


def test_paste_accepts_kind_dims(client):
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "dims-list", "title": "Working list",
            "provider": "synthetic author", "date": "2026-11-24",
            "text": PROTOTYPE_LIST, "synthetic_confirmed": True, "kind": "dims",
        },
    )
    assert response.status_code == 200, response.text
    view = _dimensions(client)
    assert view["has_list"] is True
    # Second paste with a different material_id -> 409 fixed body.
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "dims-two", "title": "Other",
            "provider": "synthetic author", "date": "2026-11-24",
            "text": "Dimension 1: Sleep", "synthetic_confirmed": True,
            "kind": "dims",
        },
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "dimension list exists"}


def test_dimension_put_fixed_error_bodies(client):
    _seed(client)
    _upload_list(client)
    view = _dimensions(client)
    item = view["items"][0]
    url = f"/api/workspaces/case-a/evidence/{item['id']}/dimension"
    # Unknown evidence -> 404 fixed body.
    response = client.put(
        "/api/workspaces/case-a/evidence/ev_missing/dimension",
        json={"action": "none"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "evidence not found"}
    # Unknown dimension id -> 400 fixed body.
    response = client.put(url, json={"dimension_id": "dim_" + "f" * 24})
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid dimension choice"}
    # Invalid bodies -> 400 (extra keys forbidden by the model).
    assert client.put(url, json={"action": "bogus"}).status_code == 400
    assert client.put(url, json={}).status_code == 400
    assert client.put(url, json={"action": "none", "dimension_id": "x"}).status_code == 400
    assert client.put(url, json={"action": "none", "extra": 1}).status_code == 400


def test_dimension_case_isolation(client):
    api = client
    assert api.post("/api/workspaces", json={"case_id": "case-b"}).status_code == 201
    _seed(api, "case-a")
    _upload_list(api, "case-a")
    api.post("/api/workspaces/case-b/synthetic-confirmation")
    _seed(api, "case-b")
    view_b = _dimensions(api, "case-b")
    assert view_b["has_list"] is False
    assert view_b["dimensions"] == []
    assert all(item["dimension_id"] is None for item in view_b["items"])


def test_evidence_get_carries_dimension_fields(client):
    _seed(client)
    _upload_list(client)
    response = client.get("/api/workspaces/case-a/evidence")
    assert response.status_code == 200
    for item in response.json()["items"]:
        assert {"dimension_id", "dimension_name", "dim_state", "dim_reason",
                "dim_set_by"} <= set(item)
    mapped = next(i for i in response.json()["items"]
                  if i["dimension_name"] == "Attention")
    assert mapped["dim_state"] == "needs_review"
    assert "The system only matched words" in mapped["dim_reason"]
