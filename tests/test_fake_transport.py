"""Offline fake transport: deterministic, never opens a socket."""

from __future__ import annotations

import socket

import pytest

from psychtool.config import Config
from psychtool.gateway.fake import FAKE_MODEL_TEXT, fake_transport
from psychtool.gateway.http import http_transport


def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in this test")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def test_fake_transport_returns_fixed_synthetic_text(monkeypatch):
    _no_network(monkeypatch)
    config = Config(base_url="https://unreachable.invalid/v1", model="fake-model")
    envelope = {"model": "fake-model", "messages": [{"role": "user", "content": "hello"}]}

    first = fake_transport(config, envelope)
    second = fake_transport(config, {"model": "other", "messages": []})

    assert first == second == FAKE_MODEL_TEXT


def test_fake_text_is_clearly_synthetic_and_has_no_diagnosis():
    lowered = FAKE_MODEL_TEXT.lower()
    assert "synthetic" in lowered
    assert "fake" in lowered
    assert "no model was called" in lowered
    for word in ("diagnos", "disorder", "depression", "adhd", "autism"):
        assert word not in lowered


def test_fake_transport_matches_http_transport_call_shape():
    assert fake_transport.__code__.co_varnames[:2] == ("config", "envelope")
    assert http_transport.__code__.co_varnames[:2] == ("config", "envelope")
