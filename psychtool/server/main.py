"""Development entrypoint: ``python -m psychtool.server``.

Binds 127.0.0.1 only (ADR 0011): any non-loopback ``PSYCHTOOL_HOST`` refuses
to start. Startup runs the security self-checks and logs one line per item;
the session token value is never printed.
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

from psychtool.server.selfcheck import DataDirError, check_data_dir_not_synced, run_self_checks
from psychtool.store.sqlite_store import default_db_path

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
_LOG_HANDLER_NAME = "psychtool-startup"


def _resolve_host() -> str:
    host = os.environ.get("PSYCHTOOL_HOST", DEFAULT_HOST)
    if host not in LOOPBACK_HOSTS:
        print(
            f"refusing to start: PSYCHTOOL_HOST={host!r} is not a loopback "
            "address; the API only ever binds 127.0.0.1",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return host


def _resolve_port() -> int:
    raw = os.environ.get("PSYCHTOOL_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw)
    except ValueError:
        print(f"refusing to start: PSYCHTOOL_PORT={raw!r} is not a port", file=sys.stderr)
        raise SystemExit(2) from None
    if not 1 <= port <= 65535:
        print(f"refusing to start: PSYCHTOOL_PORT={port} is out of range", file=sys.stderr)
        raise SystemExit(2)
    return port


def _configure_logging() -> None:
    """Show the ``psychtool`` logger's INFO lines (the self-check items).

    Without a handler, Python drops INFO records, so the startup log would
    show only warnings. Messages are fixed strings: no user text, no token.
    """
    logger = logging.getLogger("psychtool")
    for existing in [h for h in logger.handlers if h.get_name() == _LOG_HANDLER_NAME]:
        logger.removeHandler(existing)
    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_LOG_HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main() -> None:
    _configure_logging()
    host = _resolve_host()
    port = _resolve_port()
    # Cheap pre-check so a cloud-synced data dir fails before the app builds;
    # the full check also runs inside run_self_checks below.
    try:
        check_data_dir_not_synced(default_db_path())
    except DataDirError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None

    # Imported here so the data-dir check above runs before anything opens
    # the database.
    from psychtool.server.app import create_app

    app = create_app()
    run_self_checks(
        app.state.store,
        host=host,
        token_source=app.state.session_token_source,
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
