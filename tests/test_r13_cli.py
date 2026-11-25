"""R13 (PT-05 / ADR 0013): the CLI ``import`` path screens protected content.

``workspace.import_material`` is the choke point for the CLI and for eval
materials, so blocked paragraphs must never be written to the JSON material
store — not even on this path. The CLI reports the held-back count with a
fixed line and exits 1 with nothing written when the import is rejected.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from psychtool.cli.app import app

BLOCKED_MARKER = "raw 12 = T 55"
BLOCKED_TEXT = f"Norm table: {BLOCKED_MARKER}."
KEPT_TEXT = "A normal synthetic paragraph about morning routines."


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "case-a"
    result = CliRunner().invoke(app, ["init", str(ws), "--case-id", "case-a"])
    assert result.exit_code == 0, result.output
    return ws


def _import(runner, workspace, tmp_path, text):
    notes = tmp_path / "notes.md"
    notes.write_text(text, encoding="utf-8")
    return runner.invoke(
        app,
        ["import", str(workspace), "--material-id", "doc-1", "--title", "Note",
         "--provider", "synthetic author", "--date", "2026-11-24",
         "--file", str(notes)],
    )


def _material_files(workspace):
    return list((workspace / "materials").glob("*.v*.json"))


def test_cli_import_holds_back_protected_paragraph(runner, workspace, tmp_path):
    result = _import(runner, workspace, tmp_path,
                     f"{KEPT_TEXT}\n\n{BLOCKED_TEXT}\n")
    assert result.exit_code == 0, result.output
    assert "imported doc-1 v1" in result.output
    assert "held back 1 paragraph(s)" in result.output
    assert "not stored, never sent" in result.output
    # The blocked text is nowhere: not in stdout, not in the stored JSON.
    assert BLOCKED_MARKER not in result.output
    files = _material_files(workspace)
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert [p["id"] for p in stored["passages"]] == ["p001"]
    assert stored["passages"][0]["text"] == KEPT_TEXT
    assert BLOCKED_MARKER not in files[0].read_text(encoding="utf-8")


def test_cli_import_all_blocked_exits_1_writes_nothing(runner, workspace, tmp_path):
    result = _import(runner, workspace, tmp_path, f"{BLOCKED_TEXT}\n")
    assert result.exit_code == 1
    # No success line, no held-back count line; fixed message on stderr.
    assert "imported doc-1" not in result.output + result.stderr
    assert "held back 1 paragraph(s)" not in result.output + result.stderr
    assert "Paragraphs were held back" in result.stderr
    assert BLOCKED_MARKER not in result.output + result.stderr
    assert _material_files(workspace) == []


def test_cli_import_checker_failure_exits_1_writes_nothing(
    runner, workspace, tmp_path, monkeypatch
):
    import psychtool.core.protected as protected_module

    def broken(texts):
        raise RuntimeError("injected checker failure")

    monkeypatch.setattr(protected_module, "find_protected", broken)
    result = _import(runner, workspace, tmp_path, f"{KEPT_TEXT}\n")
    assert result.exit_code == 1
    assert "could not be checked" in result.stderr
    assert _material_files(workspace) == []
