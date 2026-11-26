"""Classify model endpoints and refuse Google AI Studio paths.

Vertex AI Gemini is the only supported cloud path (Q2 / ADR 0022). The
Gemini Developer API / Google AI Studio is never used, even under the
synthetic tier.
"""

from __future__ import annotations

from urllib.parse import urlparse


class AIStudioForbiddenError(RuntimeError):
    """Raised when a configured endpoint is a Google AI Studio / Gemini Developer API URL."""

    def __init__(self) -> None:
        super().__init__(
            "Google AI Studio and the Gemini Developer API are not a supported path; "
            "use Vertex AI or a local OpenAI-compatible endpoint"
        )


class VertexConfigError(RuntimeError):
    """Raised when the Vertex transport is used with a non-Vertex endpoint or incomplete config."""

    def __init__(self, message: str = "Vertex transport requires a Vertex AI endpoint") -> None:
        super().__init__(message)


class VertexAuthError(RuntimeError):
    """Raised when no Vertex access token is configured. ADC is never probed."""

    def __init__(self) -> None:
        super().__init__(
            "Vertex access token is not configured. Set PSYCHTOOL_VERTEX_ACCESS_TOKEN; "
            "application default credentials are not probed"
        )


_AISTUDIO_HOSTS = frozenset(
    {
        "generativelanguage.googleapis.com",
        "generativelanguage.google.com",
        "ai.google.dev",
        "aistudio.google.com",
        "aistudio.google.cn",
    }
)
_AISTUDIO_PATH_MARKERS = ("/v1beta/models/", "/v1beta/openai/")
_VERTEX_HOST_SUFFIX = "aiplatform.googleapis.com"


def _hostname(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_ai_studio_endpoint(url: str) -> bool:
    """True when ``url`` is a Google AI Studio / Gemini Developer API endpoint."""
    if not url:
        return False
    host = _hostname(url)
    if host in _AISTUDIO_HOSTS or host.endswith(".ai.google.dev"):
        return True
    path = urlparse(url).path.lower()
    return any(marker in path for marker in _AISTUDIO_PATH_MARKERS)


def is_vertex_endpoint(url: str) -> bool:
    """True when ``url`` is a Vertex AI (aiplatform.googleapis.com) endpoint."""
    host = _hostname(url)
    if not host:
        return False
    # Global host, or regional "{location}-aiplatform.googleapis.com".
    return host == _VERTEX_HOST_SUFFIX or host.endswith("-" + _VERTEX_HOST_SUFFIX)


def refuse_ai_studio(url: str) -> None:
    """Raise ``AIStudioForbiddenError`` if ``url`` is an AI Studio endpoint."""
    if is_ai_studio_endpoint(url):
        raise AIStudioForbiddenError()


def vertex_openapi_base_url(project: str, location: str) -> str:
    """Return the OpenAI-compatible Vertex root (no ``/chat/completions`` suffix)."""
    project = project.strip()
    location = location.strip()
    if not project or not location:
        raise VertexConfigError(
            "Vertex profile requires PSYCHTOOL_VERTEX_PROJECT and PSYCHTOOL_VERTEX_LOCATION"
        )
    host = f"{location}-aiplatform.googleapis.com"
    path = f"/v1/projects/{project}/locations/{location}/endpoints/openapi"
    return f"{'https'}://{host}{path}"
