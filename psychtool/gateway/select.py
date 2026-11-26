"""Pick the model transport from config. The offline fake is the default."""

from __future__ import annotations

from collections.abc import Callable

from psychtool.config import Config
from psychtool.gateway.fake import fake_transport
from psychtool.gateway.http import http_transport
from psychtool.gateway.vertex import vertex_transport

Transport = Callable[..., str]


def select_transport(config: Config) -> Transport:
    """Return the transport for ``config.transport``.

    ``http`` and ``vertex`` are explicit opt-ins. Anything else, including an
    unrecognised value, uses the offline fake so a typo cannot open a socket.
    """
    if config.transport == "http":
        return http_transport
    if config.transport == "vertex":
        return vertex_transport
    return fake_transport
