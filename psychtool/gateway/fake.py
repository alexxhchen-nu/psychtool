"""Offline, deterministic fake transport for the gateway.

``fake_transport`` has the same call shape as
``psychtool.gateway.http.http_transport`` but never opens a socket. It is the
default transport for the development server so the full prepare -> approve ->
send path can be exercised end to end without any network access.

The canned reply is deliberately non-clinical: it must be obviously synthetic,
must not contain a diagnosis, and must stay useful in the editor (it lands as
unsaved section text that a human then reviews and saves).
"""

from __future__ import annotations

from psychtool.config import Config

FAKE_MODEL_TEXT = (
    "FAKE OFFLINE RESPONSE — synthetic placeholder only.\n\n"
    "This text was produced by psychtool's built-in fake transport. No model "
    "was called and no network request was made. It is not clinical content "
    "and must not be treated as source material or as a reviewed draft. "
    "Replace it with your own reviewed text before saving."
)

# The canned text deliberately contains no clinical terminology so it can
# never be mistaken for model output or a clinical conclusion.


def fake_transport(config: Config, envelope: dict) -> str:
    """Return a fixed synthetic reply; ignores the envelope and never sends it."""
    _ = config, envelope
    return FAKE_MODEL_TEXT
