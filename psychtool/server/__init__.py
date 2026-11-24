"""FastAPI web server for psychtool (ADR 0009)."""

from psychtool.server.app import create_app

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    # Lazy: importing the package must not build an app or open the database.
    if name == "app":
        from psychtool.server import app as _app_module

        return _app_module.app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
