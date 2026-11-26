"""Scripted launcher checks. These run on Linux; they are not a Finder, Explorer, Gatekeeper, or SmartScreen test."""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
import textwrap
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "launchers" / "Start Psychtool.command"
CMD = ROOT / "launchers" / "Start Psychtool.cmd"

PLAIN_MISSING = (
    "This copy of psychtool isn't ready to start. "
    "Ask the person who installed it to check the installation, then try again."
)


def _install_opener(bin_dir: Path) -> None:
    script = "#!/bin/sh\nprintf '%s\n' \"$1\" >> \"$OPENED_LOG\"\n"
    for name in ("open", "xdg-open"):
        path = bin_dir / name
        path.write_text(script, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/health"):
            body = b'{"version":"0.1.0"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def test_command_script_is_executable_and_unix_line_endings():
    data = COMMAND.read_bytes()
    assert data.startswith(b"#!/bin/sh")
    assert b"\r\n" not in data
    assert COMMAND.stat().st_mode & stat.S_IXUSR


def test_cmd_script_mentions_health_url_browser_and_plain_failure():
    text = CMD.read_text(encoding="utf-8")
    assert "PSYCHTOOL_PORT" in text
    assert "127.0.0.1" in text
    assert "api/health" in text
    assert 'start "" "%URL%"' in text
    assert PLAIN_MISSING in " ".join(text.split())
    assert text.lstrip().startswith("@echo off")


def test_command_opens_browser_when_server_already_running(tmp_path):
    port = _free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), _HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opened = tmp_path / "opened.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_opener(bin_dir)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["PSYCHTOOL_PORT"] = str(port)
    env["OPENED_LOG"] = str(opened)
    try:
        result = subprocess.run(
            ["sh", str(COMMAND)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert opened.read_text(encoding="utf-8").strip() == f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        server.server_close()


def test_command_starts_fake_uv_then_opens_browser(tmp_path):
    port = _free_port()
    opened = tmp_path / "opened.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_opener(bin_dir)
    uv = bin_dir / "uv"
    uv.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import os, sys
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            port = int(os.environ["PSYCHTOOL_PORT"])
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if self.path.startswith("/api/health"):
                        body = b'{{"version":"0.1.0"}}'
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    self.send_response(404)
                    self.end_headers()
                def log_message(self, format, *args):
                    return
            # Stay in the foreground so the launcher can wait on this pid.
            ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
            """
        ),
        encoding="utf-8",
    )
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"
    env["PSYCHTOOL_PORT"] = str(port)
    env["OPENED_LOG"] = str(opened)
    proc = subprocess.Popen(
        ["sh", str(COMMAND)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            if opened.exists() and opened.read_text(encoding="utf-8").strip():
                break
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                pytest.fail(f"launcher exited early {proc.returncode}: {stderr}\n{stdout}")
            time.sleep(0.05)
        else:
            proc.kill()
            pytest.fail("launcher did not open the browser in time")
        assert opened.read_text(encoding="utf-8").strip() == f"http://127.0.0.1:{port}/"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_command_missing_uv_prints_plain_language(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = os.environ.copy()
    # Keep python3/curl out of the start path; only a tiny PATH so `uv` is missing
    # and there is no repo .venv either (cwd is tmp, script still cds to repo root).
    # Run a copy of the script from a temp tree that has no .venv.
    tree = tmp_path / "checkout"
    launchers = tree / "launchers"
    launchers.mkdir(parents=True)
    script = launchers / "Start Psychtool.command"
    script.write_bytes(COMMAND.read_bytes())
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    env["PATH"] = f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"
    env["PSYCHTOOL_PORT"] = str(_free_port())
    result = subprocess.run(
        ["sh", str(script)],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert PLAIN_MISSING in result.stderr
