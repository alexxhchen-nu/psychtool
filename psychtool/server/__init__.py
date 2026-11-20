"""FastAPI web server for psychtool (ADR 0009)."""

from psychtool.server.app import app, create_app

__all__ = ["app", "create_app"]
