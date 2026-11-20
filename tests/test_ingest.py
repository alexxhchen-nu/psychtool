from fastapi.testclient import TestClient

from psychtool.core.ingest import parse_upload
from psychtool.core.workspace import init_workspace, list_materials
from psychtool.server.app import create_app


def test_text_upload_is_local_and_flags_identifiers(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    init_workspace(root / "case-a", case_id="case-a")
    monkeypatch.setenv("PSYCHTOOL_WORKSPACES_DIR", str(root))
    response = TestClient(create_app()).post(
        "/api/workspaces/case-a/materials",
        data={"material_id": "intake", "title": "Intake", "provider": "self", "date": "2026-11-08"},
        files={"file": ("notes.txt", b"Call 312-555-0142.\n\nSleep changed.", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["requires_human_review"] is True
    assert any(hit["category"] == "telephone" for hit in response.json()["identifier_findings"])
    material = list_materials(root / "case-a")[0]
    assert len(material.passages) == 2
    assert "312-555-0142" not in material.passages[0].text
    assert "[[TELEPHONE_" in material.passages[0].text
    assert "value" not in response.json()["identifier_findings"][0]


def test_upload_rejects_unsupported_extension():
    try:
        parse_upload("script.exe", b"hello")
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unsupported upload accepted")
