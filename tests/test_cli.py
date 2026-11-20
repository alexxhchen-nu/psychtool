"""End-to-end CLI tests: subprocess against the real command surface."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

PKG = [sys.executable, "-m", "psychtool"]
_ENV_VARS = (
    "PSYCHTOOL_BASE_URL",
    "PSYCHTOOL_MODEL",
    "PSYCHTOOL_JUDGE_MODEL",
    "PSYCHTOOL_DATA_TIER",
    "PSYCHTOOL_API_KEY",
    "PSYCHTOOL_REDACT",
)


@pytest.fixture(autouse=True)
def _clear_psychtool_environment(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _run(args, env=None):
    import os
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        PKG + args, capture_output=True, text=True, env=merged
    )


@pytest.fixture
def ws(tmp_path):
    return tmp_path / "case-a"


def _material_file(tmp_path, text="背景一。\n\n背景二。"):
    p = tmp_path / "notes.txt"
    p.write_text(text, encoding="utf-8")
    return p


def test_init_and_import_and_claims(ws, tmp_path):
    r = _run(["init", str(ws), "--case-id", "case-a"])
    assert r.returncode == 0, r.stderr
    f = _material_file(tmp_path)
    r = _run(["import", str(ws), "--material-id", "doc-1", "--title", "访谈",
              "--provider", "本人", "--date", "2026-10-01", "--file", str(f)])
    assert r.returncode == 0, r.stderr
    assert (ws / "materials" / "doc-1.v1.json").exists()

    r = _run(["claims", "list", str(ws)])
    assert r.returncode == 0
    # re-import to create v2
    _run(["import", str(ws), "--material-id", "doc-1", "--title", "访谈",
          "--provider", "本人", "--date", "2026-10-02", "--file", str(f)])
    assert (ws / "materials" / "doc-1.v2.json").exists()


def test_claims_add_and_status(ws):
    _run(["init", str(ws), "--case-id", "case-a"])
    r = _run(["claims", "add", str(ws), "--id", "c1", "--doc", "doc-1",
              "--ver", "1", "--passage", "p001", "--role", "self_report",
              "--setting", "intake", "--record", "2026-10-01",
              "--category", "client_statement", "--topic", "t",
              "--text", "本人报告入睡困难。"])
    assert r.returncode == 0, r.stderr
    assert (ws / "claims" / "c1.v1.json").exists()
    r = _run(["claims", "status", str(ws), "c1", "verified"])
    assert r.returncode == 0, r.stderr
    assert (ws / "claims" / "c1.v2.json").exists()


def test_review_and_export(ws, tmp_path):
    _run(["init", str(ws), "--case-id", "case-a"])
    f = _material_file(tmp_path)
    _run(["import", str(ws), "--material-id", "doc-1", "--title", "t",
          "--provider", "p", "--date", "2026-10-01", "--file", str(f)])
    _run(["claims", "add", str(ws), "--id", "c1", "--doc", "doc-1", "--ver", "1",
          "--passage", "p001", "--role", "self_report", "--setting", "intake",
          "--record", "2026-10-01", "--category", "client_statement",
          "--topic", "t", "--text", "x"])

    r = _run(["review", str(ws)])
    assert r.returncode == 0, r.stderr
    assert "stale_claims" in r.stdout or "conflicts" in r.stdout

    # draft via a local mock model server, then export
    with _mock_model() as url:
        env = {
            "PSYCHTOOL_BASE_URL": url,
            "PSYCHTOOL_MODEL": "m1",
            "PSYCHTOOL_API_KEY": "k",
            "PSYCHTOOL_DATA_TIER": "synthetic",
        }
        r = _run(["draft", str(ws), "--claim-ids", "c1", "--instructions", "背景",
                  "--max-steps", "1", "--synthetic-auto",
                  "--approval-reason", "CLI synthetic test"], env=env)
        assert r.returncode == 0, r.stderr
        assert (ws / "drafts").exists()

        out = tmp_path / "report.md"
        r = _run(["export", str(ws), "--draft-id", "d1", "--out", str(out)])
        assert r.returncode == 0, r.stderr
        assert out.exists()


def test_help_each_command():
    for cmd in ["init", "import", "claims", "draft", "review", "export"]:
        r = _run([cmd, "--help"])
        assert r.returncode == 0, cmd


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = json.dumps({
            "choices": [{"message": {"content": "草稿正文 [c1]"}}]
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _mock_model:
    def __enter__(self):
        self.server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()
