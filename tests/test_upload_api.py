"""PT-04 (GROK-34): server upload rules, R2 acceptance criteria, R12 (M1).

- R2-AC1: an approved .txt/.md upload lands in the material list and yields
  evidence suggestions.
- R2-AC2: oversized or wrong-type uploads are rejected with a stated reason
  and write nothing (no material/passage/audit rows, no new version).
- R2-AC3: the first upload in a case is refused until the per-case synthetic
  confirmation is recorded; confirming is idempotent and survives restart.
- R12 (M1): PDFs and images are rejected with the fixed scan explanation;
  the server path never runs OCR.
- ADR 0012: the catch-all error handler returns a fixed 500 body and logs
  the exception type only — never the message.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from psychtool.core.ingest import (
    MAX_UPLOAD_BYTES,
    SCAN_NOT_SUPPORTED_MESSAGE,
    SERVER_UPLOAD_MESSAGES,
    parse_server_upload,
)
from psychtool.server.app import create_app
from psychtool.store.sqlite_store import SqliteStore
from tests.conftest import build_client

MARKER = "ZEBRA-UPLOAD-MARKER-91c2"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "psychtool.db"
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db_path):
    api = build_client(create_app())
    assert api.post("/api/workspaces", json={"case_id": "case-a"}).status_code == 201
    return api


def _confirm(client, case_id="case-a"):
    response = client.post(f"/api/workspaces/{case_id}/synthetic-confirmation")
    assert response.status_code == 200
    assert response.json()["synthetic_confirmed"] is True


def _upload(client, filename="notes.txt", data=b"Synthetic paragraph one.\n\nSynthetic two.",
            material_id="doc-1", case_id="case-a"):
    return client.post(
        f"/api/workspaces/{case_id}/materials",
        data={"material_id": material_id, "title": "Synthetic note",
              "provider": "synthetic author", "date": "2026-11-24"},
        files={"file": (filename, data, "application/octet-stream")},
    )


def _table_counts(db_path):
    raw = sqlite3.connect(db_path)
    counts = {
        table: raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("materials", "passages", "audit_log")
    }
    raw.close()
    return counts


# -- R2-AC3: first-upload confirmation --------------------------------------


def test_r2_ac3_upload_refused_before_confirmation(client, db_path):
    before = _table_counts(db_path)
    response = _upload(client)
    assert response.status_code == 409
    assert response.json()["reason"] == "confirmation_required"
    assert _table_counts(db_path) == before


def test_r2_ac3_case_detail_exposes_the_flag(client):
    detail = client.get("/api/workspaces/case-a").json()
    assert detail == {"case_id": "case-a", "synthetic_confirmed": False}
    _confirm(client)
    detail = client.get("/api/workspaces/case-a").json()
    assert detail["synthetic_confirmed"] is True


def test_r2_ac3_confirmation_is_idempotent_and_audited_once(client, db_path):
    _confirm(client)
    _confirm(client)  # second call must not append a second audit row
    raw = sqlite3.connect(db_path)
    rows = raw.execute(
        "SELECT action, object_type, object_id FROM audit_log"
        " WHERE action = 'case.confirm_synthetic'"
    ).fetchall()
    raw.close()
    assert rows == [("case.confirm_synthetic", "case", "case-a")]


def test_r2_ac3_confirmation_persists_across_restart(client, db_path):
    _confirm(client)
    # A new app over the same database file must not ask again.
    reopened = build_client(create_app())
    assert reopened.get("/api/workspaces/case-a").json()["synthetic_confirmed"] is True
    assert _upload(reopened).status_code == 200


def test_r2_ac3_confirmed_paste_records_the_case_confirmation(client):
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "paste-1",
            "title": "Pasted synthetic note",
            "provider": "synthetic author",
            "date": "2026-11-24",
            "text": "Synthetic pasted paragraph.",
            "synthetic_confirmed": True,
        },
    )
    assert response.status_code == 200
    assert client.get("/api/workspaces/case-a").json()["synthetic_confirmed"] is True
    assert _upload(client).status_code == 200


def test_r2_ac3_unconfirmed_paste_does_not_confirm_the_case(client):
    response = client.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "paste-1",
            "title": "Pasted synthetic note",
            "provider": "synthetic author",
            "date": "2026-11-24",
            "text": "Synthetic pasted paragraph.",
            "synthetic_confirmed": False,
        },
    )
    assert response.status_code == 400
    assert client.get("/api/workspaces/case-a").json()["synthetic_confirmed"] is False


# -- R2-AC1: accepted uploads -----------------------------------------------


def test_r2_ac1_txt_upload_appears_in_list_and_yields_suggestions(client):
    _confirm(client)
    response = _upload(client, filename="intake.txt",
                       data=b"Synthetic first paragraph.\n\nSynthetic second paragraph.")
    assert response.status_code == 200
    material = response.json()["material"]
    assert material["id"] == "doc-1"
    assert material["version"] == 1
    assert [p["text"] for p in material["passages"]] == [
        "Synthetic first paragraph.",
        "Synthetic second paragraph.",
    ]

    listed = client.get("/api/workspaces/case-a/materials").json()
    assert [m["id"] for m in listed] == ["doc-1"]

    suggestions = client.get(
        "/api/workspaces/case-a/materials/doc-1/suggestions",
        params={"provider_role": "self_report"},
    )
    assert suggestions.status_code == 200
    candidates = suggestions.json()
    assert len(candidates) == 2
    assert candidates[0]["source_document_id"] == "doc-1"
    assert candidates[0]["source_version"] == 1


def test_r2_ac1_md_upload_with_bom_is_accepted(client):
    _confirm(client)
    response = _upload(client, filename="notes.md",
                       data="\ufeff# Synthetic heading\n\nSynthetic body.".encode("utf-8"))
    assert response.status_code == 200
    passages = response.json()["material"]["passages"]
    assert passages[0]["text"] == "# Synthetic heading"  # BOM stripped


def test_r2_ac1_same_id_reupload_creates_next_immutable_version(client):
    _confirm(client)
    first = _upload(client, data=b"Synthetic v1 text.")
    second = _upload(client, data=b"Synthetic v2 text.")
    assert first.json()["material"]["version"] == 1
    assert second.json()["material"]["version"] == 2

    listed = client.get("/api/workspaces/case-a/materials").json()
    assert len(listed) == 1
    assert listed[0]["version"] == 2
    assert listed[0]["passages"][0]["text"] == "Synthetic v2 text."
    # v1 remains stored unchanged (immutable versions).
    store = SqliteStore(client.app.state.store.path)
    v1 = store.case("case-a").get_material("doc-1", version=1)
    assert v1.passages[0].text == "Synthetic v1 text."


# -- R2-AC2 / R12: rejections write nothing ----------------------------------


def test_r2_ac2_oversized_upload_rejected_with_reason(client, db_path):
    _confirm(client)
    before = _table_counts(db_path)
    response = _upload(client, data=b"x" * (MAX_UPLOAD_BYTES + 1))
    assert response.status_code == 413
    body = response.json()
    assert body["reason"] == "too_large"
    assert body["detail"] == SERVER_UPLOAD_MESSAGES["too_large"]
    assert _table_counts(db_path) == before


@pytest.mark.parametrize("filename", ["scan.pdf", "scan.png", "scan.jpg", "scan.jpeg"])
def test_r12_scans_and_images_rejected_with_fixed_explanation(client, db_path, filename):
    _confirm(client)
    before = _table_counts(db_path)
    response = _upload(client, filename=filename)
    assert response.status_code == 400
    body = response.json()
    assert body["reason"] == "scan_not_supported"
    assert body["detail"] == SCAN_NOT_SUPPORTED_MESSAGE
    assert _table_counts(db_path) == before


@pytest.mark.parametrize("filename", ["notes.docx", "notes", "notes.exe", "notes.gif"])
def test_r2_ac2_other_types_rejected_with_reason(client, db_path, filename):
    _confirm(client)
    before = _table_counts(db_path)
    response = _upload(client, filename=filename)
    assert response.status_code == 400
    body = response.json()
    assert body["reason"] == "unsupported_type"
    assert body["detail"] == SERVER_UPLOAD_MESSAGES["unsupported_type"]
    assert _table_counts(db_path) == before


def test_r2_ac2_non_utf8_text_rejected_with_reason(client, db_path):
    _confirm(client)
    before = _table_counts(db_path)
    response = _upload(client, filename="notes.txt", data=b"\xff\xfe invalid \xff")
    assert response.status_code == 400
    body = response.json()
    assert body["reason"] == "not_utf8"
    assert body["detail"] == SERVER_UPLOAD_MESSAGES["not_utf8"]
    assert _table_counts(db_path) == before


def test_r2_ac2_empty_text_rejected_with_reason(client, db_path):
    _confirm(client)
    before = _table_counts(db_path)
    response = _upload(client, data=b"   \n\n  ")
    assert response.status_code == 400
    assert response.json()["reason"] == "empty"
    assert _table_counts(db_path) == before


def test_rejection_never_echoes_filename_or_content(client, db_path):
    _confirm(client)
    for filename, data in (
        (f"{MARKER}.pdf", b"whatever"),
        (f"{MARKER}.docx", b"whatever"),
        (f"{MARKER}.txt", b"\xff\xfe" + MARKER.encode()),
        (f"{MARKER}.txt", b"x" * (MAX_UPLOAD_BYTES + 1)),
    ):
        response = _upload(client, filename=filename, data=data)
        assert response.status_code in (400, 413)
        assert MARKER not in response.text


def test_rejection_after_prior_upload_keeps_existing_version(client, db_path):
    _confirm(client)
    assert _upload(client, data=b"Synthetic v1 text.").status_code == 200
    before = _table_counts(db_path)
    response = _upload(client, filename="scan.pdf")
    assert response.status_code == 400
    assert _table_counts(db_path) == before
    listed = client.get("/api/workspaces/case-a/materials").json()
    assert listed[0]["version"] == 1


def test_parse_server_upload_never_runs_ocr():
    # The CLI OCR branch is unreachable from the server parser: a PDF raises
    # the fixed scan rejection before any converter could be invoked.
    with pytest.raises(Exception) as excinfo:
        parse_server_upload("scan.pdf", b"%PDF-1.4 fake")
    assert getattr(excinfo.value, "reason", None) == "scan_not_supported"


# -- ADR 0012: catch-all error handler ---------------------------------------


@pytest.fixture
def raising_client(db_path, monkeypatch):
    app = create_app()

    @app.get("/api/workspaces/{case_id}/boom")
    def boom(case_id: str):  # pragma: no cover - trivially raises
        _ = case_id
        raise RuntimeError(f"{MARKER} secret text")

    # create_app registers the SPA catch-all /{full_path:path} when web/dist
    # exists; it would shadow /boom. Move the test route ahead of it.
    boom_route = app.routes.pop()
    app.routes.insert(0, boom_route)

    return build_client(app, raise_server_exceptions=False)


def test_catch_all_returns_fixed_500_and_logs_type_only(raising_client, caplog):
    with caplog.at_level(logging.DEBUG):
        response = raising_client.get("/api/workspaces/case-a/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal error"}
    # PT-03 security headers still apply to the 500 response.
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")

    messages = [record.getMessage() for record in caplog.records]
    assert any("unhandled error: RuntimeError" in message for message in messages)
    for record in caplog.records:
        assert MARKER not in record.getMessage()


def test_catch_all_logs_exactly_one_line(raising_client, caplog):
    with caplog.at_level(logging.DEBUG, logger="psychtool"):
        raising_client.get("/api/workspaces/case-a/boom")
    own = [r for r in caplog.records if r.name == "psychtool"]
    assert [r.getMessage() for r in own] == ["unhandled error: RuntimeError"]


def test_uvicorn_error_filter_reduces_traceback_records():
    from psychtool.server.main import UvicornErrorTraceFilter

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception in ASGI application",
        args=(),
        exc_info=None,
    )
    try:
        raise RuntimeError(f"{MARKER} secret text")
    except RuntimeError:
        import sys

        record.exc_info = sys.exc_info()
    assert UvicornErrorTraceFilter().filter(record) is True
    assert record.getMessage() == "unhandled error: RuntimeError"
    assert record.exc_info is None
    assert record.exc_text is None
    # Non-exception records pass through untouched.
    plain = logging.LogRecord(
        name="uvicorn.error", level=logging.INFO, pathname=__file__, lineno=1,
        msg="Started server process [1]", args=(), exc_info=None,
    )
    assert UvicornErrorTraceFilter().filter(plain) is True
    assert plain.getMessage() == "Started server process [1]"


def test_uvicorn_server_stderr_never_contains_exception_text(db_path):
    """Real uvicorn subprocess: the marker must not reach its stderr."""
    import os
    import socket
    import subprocess
    import sys
    import time
    import urllib.error
    import urllib.request
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    env_token = "e" * 40
    script = (
        "from psychtool.server.app import create_app\n"
        "from psychtool.server.main import _uvicorn_log_config\n"
        "import uvicorn\n"
        "app = create_app()\n"
        "@app.get('/api/workspaces/{case_id}/boom')\n"
        "def boom(case_id: str):\n"
        f"    raise RuntimeError({MARKER!r} + ' secret text')\n"
        "# The SPA catch-all would shadow /boom when web/dist exists; move the\n"
        "# test route ahead of it.\n"
        "app.routes.insert(0, app.routes.pop())\n"
        "uvicorn.run(app, host='127.0.0.1', port="
        + str(port)
        + ", log_config=_uvicorn_log_config())\n"
    )
    env = dict(os.environ)
    env["PSYCHTOOL_DB_PATH"] = str(db_path)
    env["PSYCHTOOL_SESSION_TOKEN"] = env_token
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=2
                ) as health:
                    assert health.status == 200
                break
            except Exception:
                time.sleep(0.2)
        else:  # pragma: no cover - server never came up
            raise AssertionError("uvicorn subprocess did not start")

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/workspaces/case-a/boom",
            headers={"X-Psychtool-Token": env_token},
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("boom route unexpectedly succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 500
            assert exc.read().decode() == '{"detail":"internal error"}'
    finally:
        process.kill()
        _, stderr = process.communicate(timeout=10)

    assert "unhandled error: RuntimeError" in stderr
    assert MARKER not in stderr
    assert "Traceback" not in stderr
