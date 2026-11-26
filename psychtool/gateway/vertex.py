"""Vertex AI Gemini transport (OpenAI-compatible, stdlib only).

Used only after the gateway has validated an approved request. The gateway
refuses non-local endpoints under ``real`` before this transport is reached.
This transport also refuses Google AI Studio URLs and any non-Vertex host.
It never probes application default credentials; tests inject a token
provider, and production uses ``PSYCHTOOL_VERTEX_ACCESS_TOKEN`` only.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable

from psychtool.config import Config, ENV_VERTEX_ACCESS_TOKEN
from psychtool.gateway.endpoints import (
    VertexAuthError,
    VertexConfigError,
    is_vertex_endpoint,
    refuse_ai_studio,
)


def _token_from_env() -> str:
    token = os.environ.get(ENV_VERTEX_ACCESS_TOKEN, "").strip()
    if not token:
        raise VertexAuthError()
    return token


def vertex_transport(
    config: Config,
    envelope: dict,
    *,
    token_provider: Callable[[], str] | None = None,
) -> str:
    """POST the approved envelope unchanged to a Vertex OpenAI-compatible endpoint."""
    refuse_ai_studio(config.base_url)
    if not is_vertex_endpoint(config.base_url):
        raise VertexConfigError()
    token = (token_provider or _token_from_env)()
    url = config.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(envelope).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]
