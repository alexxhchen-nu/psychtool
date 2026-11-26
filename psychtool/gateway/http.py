"""Real HTTP transport for the gateway (stdlib only, OpenAI-compatible).

Only used after the gateway has validated an approved request; the gateway
refuses non-local endpoints under ``real`` before this transport is reached.
"""

from __future__ import annotations

import json
import urllib.request

from psychtool.config import Config
from psychtool.gateway.endpoints import refuse_ai_studio


def http_transport(config: Config, envelope: dict) -> str:
    """POST the approved envelope unchanged to the configured endpoint."""
    refuse_ai_studio(config.base_url)
    url = config.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(envelope).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    # Bypass any system proxy: model traffic goes direct to base_url,
    # and a local mock server must not be routed through an external proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]
