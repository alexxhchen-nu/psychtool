"""PT-15: the developer spot-check script runs on synthetic data only."""

from __future__ import annotations

from psychtool.acceptance.spotcheck import CHECK_IDS, main

# Re-export expected ids from the module once added; fallback list below
# is kept in sync by test_spotcheck_prints_every_item.


def test_spotcheck_passes_on_synthetic_data(capsys):
    assert main() == 0
    out = capsys.readouterr().out
    assert "synthetic data only" in out
    assert "No report export is written." in out
    assert "Not the PRD §5 product-success gate" in out
    assert "10 passed, 0 failed, 10 items" in out
    for item_id in CHECK_IDS:
        assert item_id in out, item_id
        # The item line must show PASS, not FAIL.
        line = next(row for row in out.splitlines() if row.startswith(item_id))
        assert "PASS" in line
        assert "FAIL" not in line


def test_spotcheck_cli_entrypoint_is_documented():
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "spotcheck.py"
    text = script.read_text(encoding="utf-8")
    assert "psychtool.acceptance.spotcheck" in text
    assert "never writes a report export" in text


def test_spotcheck_restores_process_environment(monkeypatch, capsys):
    import os

    monkeypatch.delenv("PSYCHTOOL_DB_PATH", raising=False)
    monkeypatch.setenv("PSYCHTOOL_TRANSPORT", "sentinel-transport")
    assert main() == 0
    capsys.readouterr()
    assert "PSYCHTOOL_DB_PATH" not in os.environ
    assert os.environ["PSYCHTOOL_TRANSPORT"] == "sentinel-transport"
