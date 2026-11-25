"""Development entrypoint: ``python -m psychtool.server``.

Binds 127.0.0.1 only (ADR 0011): any non-loopback ``PSYCHTOOL_HOST`` refuses
to start. Startup runs the security self-checks and logs one line per item;
the session token value is never printed.

Unhandled errors (ADR 0012): the app's catch-all handler logs the exception
*type* only, but Starlette's ServerErrorMiddleware re-raises after any 500
handler, and uvicorn then logs "Exception in ASGI application" with the full
traceback on ``uvicorn.error`` — which can quote request data. ``main``
therefore runs uvicorn with a ``log_config`` that attaches a filter reducing
those records to the exception type name (see
:class:`UvicornErrorTraceFilter`).
"""

from __future__ import annotations

import copy
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
_UVICORN_ERROR_LOGGER = "uvicorn.error"


class UvicornErrorTraceFilter(logging.Filter):
    """Reduce ``uvicorn.error`` records that carry a traceback to type-only.

    uvicorn's ``run_asgi`` does ``logger.error("Exception in ASGI
    application", exc_info=True)`` whenever an exception escapes the app —
    including after the catch-all 500 handler, because Starlette's
    ServerErrorMiddleware re-raises. The traceback message can quote request
    or material text, so this filter rewrites such records to contain only
    the exception class name and drops ``exc_info``/``exc_text`` before any
    handler formats them. Records without an exception pass through
    unchanged (uvicorn's normal startup lines keep their text).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc_type = record.exc_info[0]
            record.msg = f"unhandled error: {getattr(exc_type, '__name__', 'unknown')}"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def _uvicorn_log_config() -> dict:
    """uvicorn's default log config plus the type-only error filter.

    Built from the installed uvicorn's own ``LOGGING_CONFIG`` (deep-copied,
    never mutated) so access logs and formatting stay stock; the only change
    is attaching the filter to whatever handlers the ``uvicorn.error`` logger
    actually has — and, if it has none (uvicorn 0.54 leaves it handler-less so
    records propagate to the ``uvicorn`` logger's handler), to the handler(s)
    of the nearest ancestor logger that does. Passed to ``uvicorn.run`` so it
    applies before the server starts serving.
    """
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    filters = config.setdefault("filters", {})
    filters["psychtool_type_only_errors"] = {
        "()": "psychtool.server.main.UvicornErrorTraceFilter"
    }
    loggers = config.get("loggers", {})
    handlers_cfg = config.get("handlers", {})
    # Walk uvicorn.error -> uvicorn until a logger with handlers is found.
    parts = _UVICORN_ERROR_LOGGER.split(".")
    handler_names: list[str] = []
    while parts:
        logger_cfg = loggers.get(".".join(parts), {})
        handler_names = list(logger_cfg.get("handlers", []))
        if handler_names:
            break
        parts.pop()
    for handler_name in handler_names:
        handler = handlers_cfg.get(handler_name)
        if handler is not None:
            handler.setdefault("filters", []).append("psychtool_type_only_errors")
    return config


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
    # Passed as log_config (not applied here) so uvicorn installs the filter
    # before serving; a test that replaces uvicorn.run never configures
    # logging at all.
    uvicorn.run(app, host=host, port=port, log_config=_uvicorn_log_config())


if __name__ == "__main__":
    main()
