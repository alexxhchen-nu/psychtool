"""Startup deliverable (GROK-33): the server log shows the passed self-check
items, and a cloud-synced data dir is refused before the database is opened."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from psychtool.server import main as server_main

REPO = Path(__file__).resolve().parents[1]


def test_main_prints_self_check_ok_lines(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PSYCHTOOL_HOST", raising=False)
    monkeypatch.delenv("PSYCHTOOL_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(tmp_path / "psychtool.db"))
    started = {}
    monkeypatch.setattr(
        server_main.uvicorn, "run", lambda app, host, port: started.update(host=host, port=port)
    )

    server_main.main()

    err = capsys.readouterr().err
    for line in (
        "self-check ok: bind 127.0.0.1",
        "self-check ok: session token: generated (not shown)",
        "self-check ok: Host header restricted to loopback names",
        "self-check ok: strict Content-Security-Policy on all responses",
        "self-check ok: data dir is not inside a cloud-sync folder",
        "self-check ok: audit chain verified (0 entries)",
        "self-check ok: stale send-lock recovery: 0 recovered",
    ):
        assert line in err, line
    assert started == {"host": "127.0.0.1", "port": 8000}


def test_synced_data_dir_refused_before_database_is_created(tmp_path):
    db = tmp_path / "Dropbox" / "psychtool" / "psychtool.db"
    db.parent.mkdir(parents=True)
    env = dict(os.environ, PSYCHTOOL_DB_PATH=str(db))
    env.pop("PSYCHTOOL_HOST", None)
    result = subprocess.run(
        [sys.executable, "-m", "psychtool.server"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "dropbox cloud-sync folder" in result.stderr.lower()
    assert not db.exists()
