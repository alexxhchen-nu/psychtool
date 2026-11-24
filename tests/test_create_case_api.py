"""Browser case creation: ``POST /api/workspaces`` reusing ``init_workspace``."""

import pytest
from fastapi.testclient import TestClient

from psychtool.server.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_WORKSPACES_DIR", str(tmp_path))
    return TestClient(create_app())


def test_create_case_creates_workspace(client, tmp_path):
    response = client.post("/api/workspaces", json={"case_id": "case-b"})

    assert response.status_code == 201
    assert response.json() == {"case_id": "case-b"}
    assert (tmp_path / "case-b" / "meta.json").is_file()
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
