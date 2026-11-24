"""Browser case creation: ``POST /api/workspaces`` against the SQLite store."""

import pytest
from fastapi.testclient import TestClient

from psychtool.server.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    return TestClient(create_app())


def test_create_case_creates_workspace(client, tmp_path):
    response = client.post("/api/workspaces", json={"case_id": "case-b"})

    assert response.status_code == 201
    assert response.json() == {"case_id": "case-b"}
    assert (tmp_path / "psychtool.db").is_file()
    assert client.get("/api/workspaces").json() == [{"case_id": "case-b"}]


def test_create_case_rejects_duplicate(client):
    assert client.post("/api/workspaces", json={"case_id": "case-b"}).status_code == 201

    response = client.post("/api/workspaces", json={"case_id": "case-b"})

    assert response.status_code == 409
    assert response.json() == {"detail": "case already exists"}


@pytest.mark.parametrize("case_id", ["", "..", "../escape", "a/b", " spaced", "-lead", "x" * 65, "case.1"])
def test_create_case_rejects_bad_ids(client, case_id):
    response = client.post("/api/workspaces", json={"case_id": case_id})

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid request"}


def test_create_case_rejects_extra_fields(client):
    response = client.post(
        "/api/workspaces", json={"case_id": "case-b", "data_tier": "real"}
    )

    assert response.status_code == 400


def test_create_case_maps_concurrent_insert_race_to_409(client, monkeypatch):
    """Two concurrent creates of the same id: the loser's INSERT raises the
    store's ``CaseExistsError`` after the exists-check, which must surface as
    409 rather than a 500."""
    import importlib

    # The psychtool.server package re-exports a FastAPI ``app`` object, so
    # attribute access shadows the submodule; import it directly.
    app_module = importlib.import_module("psychtool.server.app")
    from psychtool.store.sqlite_store import CaseExistsError

    def _racy_create(self, case_id, *, data_tier="synthetic"):
        raise CaseExistsError(f"case already exists: {case_id}")

    monkeypatch.setattr(app_module.SqliteStore, "create_case", _racy_create)
    response = client.post("/api/workspaces", json={"case_id": "case-c"})

    assert response.status_code == 409
    assert response.json() == {"detail": "case already exists"}
