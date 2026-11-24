from fastapi.testclient import TestClient

from psychtool.core.ingest import parse_upload
from psychtool.server.app import create_app
from psychtool.store.sqlite_store import SqliteStore


def test_text_upload_is_local_and_flags_identifiers(tmp_path, monkeypatch):
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)
    store.create_case("case-a")
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(db_path))
    response = TestClient(create_app()).post(
        "/api/workspaces/case-a/materials",
        data={"material_id": "intake", "title": "Intake", "provider": "self", "date": "2026-11-08"},
        files={"file": ("notes.txt", b"Call 312-555-0142.\n\nSleep changed.", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["requires_human_review"] is True
    assert any(hit["category"] == "telephone" for hit in response.json()["identifier_findings"])
    material = store.case("case-a").list_materials()[0]
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
