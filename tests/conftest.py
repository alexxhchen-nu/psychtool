"""Shared test fixtures.

``make_client`` builds a ``TestClient`` that satisfies the PT-03 security
baseline (ADR 0011): a loopback ``Host`` header and the app's per-start
session token preset on every request. Tests keep their own fixtures and
assertions; only the client construction is shared.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from psychtool.server.app import create_app


def build_client(
    app: FastAPI, *, token: str | None = None, raise_server_exceptions: bool = True
) -> TestClient:
    """A TestClient with loopback Host and the session token preset."""
    session = token if token is not None else app.state.session_token
    return TestClient(
        app,
        base_url="http://127.0.0.1",
        headers={"X-Psychtool-Token": session},
        raise_server_exceptions=raise_server_exceptions,
    )


@pytest.fixture
def make_client():
    """Factory fixture: ``client = make_client(create_app())``."""
    return build_client
