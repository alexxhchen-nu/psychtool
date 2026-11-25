"""A-001 fixture import: JSON workspace -> SQLite store roundtrip."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from psychtool.cli.app import app
from psychtool.store.sqlite_store import CaseExistsError, SqliteStore

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "case_a001"


def _fixture_materials() -> dict[str, dict]:
    materials = {}
    for path in sorted((FIXTURE_DIR / "materials").glob("*.v*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        materials[data["id"]] = data
    return materials


def test_import_a001_reads_back_all_five_materials(tmp_path):
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)

    case_id = store.import_workspace(FIXTURE_DIR)

    assert case_id == "case-a001"
    case = store.case("case-a001")
    expected = _fixture_materials()
    assert sorted(expected) == ["m1", "m2", "m3", "m4", "m5"]

    materials = case.list_materials()
    assert [m.id for m in materials] == ["m1", "m2", "m3", "m4", "m5"]
    for material in materials:
        fixture = expected[material.id]
        assert material.version == fixture["version"]
        assert material.title == fixture["title"]
        assert material.provider == fixture["provider"]
        assert material.date == fixture["date"]
        # Passage text must round-trip verbatim, including escaped quotes.
        assert [p.id for p in material.passages] == [p["id"] for p in fixture["passages"]]
        assert [p.text for p in material.passages] == [
            p["text"] for p in fixture["passages"]
        ]

    # m3's escaped quotes survived intact.
    m3 = case.get_material("m3")
    assert '\\"move around\\"' not in m3.passages[0].text
    assert '"move around"' in m3.passages[0].text

    # Everything is scoped to case-a001: a second case sees none of it.
    store.create_case("case-other")
    assert store.case("case-other").list_materials() == []


def test_import_a001_rejects_duplicate_case(tmp_path):
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)
    store.import_workspace(FIXTURE_DIR)
    with pytest.raises(CaseExistsError):
        store.import_workspace(FIXTURE_DIR)


def test_import_json_cli_command(tmp_path):
    db_path = tmp_path / "psychtool.db"
    runner = CliRunner()

    result = runner.invoke(
        app, ["import-json", str(FIXTURE_DIR), "--db", str(db_path)]
    )

    assert result.exit_code == 0, result.output
    assert "case-a001" in result.output

    case = SqliteStore(db_path).case("case-a001")
    assert [m.id for m in case.list_materials()] == ["m1", "m2", "m3", "m4", "m5"]


def test_import_json_cli_rejects_duplicate(tmp_path):
    db_path = tmp_path / "psychtool.db"
    runner = CliRunner()
    assert runner.invoke(app, ["import-json", str(FIXTURE_DIR), "--db", str(db_path)]).exit_code == 0

    result = runner.invoke(app, ["import-json", str(FIXTURE_DIR), "--db", str(db_path)])

    assert result.exit_code != 0


def test_import_json_cli_rejects_bad_directory(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app, ["import-json", str(tmp_path / "no-such-dir"), "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code != 0


def test_import_json_defaults_to_psychtool_db_path_env(tmp_path, monkeypatch):
    """Without --db the import must land in the same file the server uses."""
    db_path = tmp_path / "env-selected.db"
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(db_path))
    runner = CliRunner()

    result = runner.invoke(app, ["import-json", str(FIXTURE_DIR)])

    assert result.exit_code == 0, result.output
    assert db_path.is_file()
    case = SqliteStore(db_path).case("case-a001")
    assert [m.id for m in case.list_materials()] == ["m1", "m2", "m3", "m4", "m5"]


def test_import_rejects_non_synthetic_workspace(tmp_path):
    """M1 is synthetic-only: data_tier other than 'synthetic' aborts the import."""
    workspace = tmp_path / "real-workspace"
    materials = workspace / "materials"
    materials.mkdir(parents=True)
    (workspace / "meta.json").write_text(
        json.dumps(
            {
                "case_id": "case-real",
                "data_tier": "real",
                "created_at": "2026-11-24T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (workspace / "identifiers.json").write_text("[]", encoding="utf-8")
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)

    with pytest.raises(ValueError, match="synthetic"):
        store.import_workspace(workspace)

    # Nothing was written: the case does not exist and a retry with a fixed
    # (synthetic) meta.json succeeds cleanly.
    assert not store.case_exists("case-real")
    (workspace / "meta.json").write_text(
        json.dumps(
            {
                "case_id": "case-real",
                "data_tier": "synthetic",
                "created_at": "2026-11-24T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    assert store.import_workspace(workspace) == "case-real"
