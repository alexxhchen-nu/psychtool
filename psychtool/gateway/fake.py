"""Offline, deterministic fake transport for the gateway.

``fake_transport`` has the same call shape as
``psychtool.gateway.http.http_transport`` but never opens a socket. It is the
default transport for the development server so the full prepare -> approve ->
send path can be exercised end to end without any network access.

The canned reply is deliberately non-clinical: it must be obviously synthetic,
must not contain a diagnosis, and must stay useful in the editor (it lands as
unsaved section text that a human then reviews and saves). When the envelope
carries ``<source_material>`` claims, the reply also echoes one claim quote
as a cited sentence and always includes one unsourced sentence, so citation
checking can be exercised offline.
"""

from __future__ import annotations

import re

from psychtool.config import Config

FAKE_MODEL_PREFIX = "FAKE OFFLINE RESPONSE — synthetic placeholder only."
FAKE_UNSOURCED_SENTENCE = (
    "This unsourced sentence is a synthetic placeholder and is not taken "
    "from the case materials."
)
FAKE_MODEL_EXPLANATION = (
    "This text was produced by psychtool's built-in fake transport. No model "
    "was called and no network request was made. It is not clinical content "
    "and must not be treated as source material or as a reviewed draft. "
    "Replace it with your own reviewed text before saving."
)
FAKE_MODEL_TEXT = (
    f"{FAKE_MODEL_PREFIX}\n\n{FAKE_UNSOURCED_SENTENCE} {FAKE_MODEL_EXPLANATION}"
)

# Require the opening tag to sit on its own line so the instruction text
# "依据下方 <source_material> 中列出的候选陈述" is not treated as the block.
_SOURCE_MATERIAL = re.compile(
    r"<source_material>\s*\n(.*)</source_material>",
    re.DOTALL | re.IGNORECASE,
)
_TERMINATORS = ".!?。！？"


def _message_content(envelope: dict) -> str:
    messages = envelope.get("messages") if isinstance(envelope, dict) else None
    if not isinstance(messages, list):
        return ""
    parts: list[str] = []
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            parts.append(message["content"])
    return "\n".join(parts)


def first_source_quote(envelope: dict) -> str | None:
    """Return the first claim quote inside ``<source_material>``, if any."""
    match = _SOURCE_MATERIAL.search(_message_content(envelope))
    if match is None:
        return None
    body = match.group(1).strip()
    if not body:
        return None
    for block in re.split(r"\n\s*\n", body):
        lines = block.strip().splitlines()
        if not lines:
            continue
        first = lines[0].lstrip()
        if first.startswith("[") and "]" in first:
            text = "\n".join(lines[1:]).strip()
        else:
            text = "\n".join(lines).strip()
        if len(text) >= 6:
            if text[-1] not in _TERMINATORS:
                text = f"{text}."
            return text
    return None


def compose_fake_reply(envelope: dict) -> str:
    """Build the deterministic fake reply for this envelope."""
    quote = first_source_quote(envelope)
    if quote is None:
        return FAKE_MODEL_TEXT
    return f"{FAKE_MODEL_PREFIX}\n\n{quote}\n\n{FAKE_UNSOURCED_SENTENCE} {FAKE_MODEL_EXPLANATION}"


# The canned text deliberately contains no clinical terminology so it can
# never be mistaken for model output or a clinical conclusion.


def fake_transport(config: Config, envelope: dict) -> str:
    """Return a deterministic synthetic reply and never send the envelope."""
    _ = config
    return compose_fake_reply(envelope)
