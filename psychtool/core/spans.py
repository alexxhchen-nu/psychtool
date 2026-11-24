"""Evidence spans (PT-06 / GROK-36, ADR 0014).

A :class:`Span` locates one verbatim quote inside one passage of one exact
material version. Offsets are **Unicode code-point** indices into that
passage's text (``0 <= start < end <= len(text)``) — the same contract the
frontend's ``highlightParts`` implements with ``Array.from`` so Python and
JavaScript always agree, even with astral-plane characters.

Everything here is pure and verbatim: no normalization, no strip, no repair.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from psychtool.core.workspace import Material, Passage


class Span(BaseModel):
    """Code-point offsets of a quote inside one passage of one version."""

    material_id: str
    material_version: int = Field(ge=1)
    passage_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _well_formed(self) -> "Span":
        if self.start >= self.end:
            raise ValueError("span must satisfy start < end")
        return self


def _find_passage(material: Material, span: Span) -> Passage | None:
    """The passage this span points at, or None on any mismatch.

    Never raises: a wrong material id/version or an unknown passage id is a
    verification failure, not an error.
    """
    if span.material_id != material.id or span.material_version != material.version:
        return None
    for passage in material.passages:
        if passage.id == span.passage_id:
            return passage
    return None


def span_text(material: Material, span: Span) -> str:
    """Return ``passage.text[start:end]``.

    Raises :class:`ValueError` for a wrong material id/version or an unknown
    passage id; out-of-range bounds (an end past the stored text) raise
    :class:`IndexError`, matching plain Python slicing semantics — callers
    that want a boolean should use :func:`verify_quote` instead.
    """
    passage = _find_passage(material, span)
    if passage is None:
        raise ValueError("span does not belong to this material")
    if span.end > len(passage.text):
        raise IndexError("span end is out of range")
    return passage.text[span.start : span.end]


def verify_quote(material: Material, span: Span, quote: str) -> bool:
    """True only when ``passage.text[start:end] == quote`` verbatim.

    False for a wrong material id/version, an unknown passage, bad bounds or
    an empty quote. No normalization, no strip — the quote matches exactly or
    not at all (extract_evidence drops non-matches, never repairs them).
    """
    if not quote:
        return False
    passage = _find_passage(material, span)
    if passage is None:
        return False
    if not (0 <= span.start < span.end <= len(passage.text)):
        return False
    return passage.text[span.start : span.end] == quote
