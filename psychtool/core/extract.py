"""Evidence extraction (PT-06 / GROK-36, ADR 0014).

R4: evidence is for the clinician's review, not a conclusion. In M1 the only
extractor is :class:`RuleExtractor` (Q4 decision: local rules, no model calls),
a port of the prototype ``buildCase`` sentence heuristic. Every candidate is
checked verbatim against its source span (:func:`extract_evidence` drops —
never repairs — any candidate whose quote is not exactly
``passage.text[start:end]``), and candidates are never merged,
de-duplicated or collapsed: identical or contradictory sentences in different
passages/materials stay as separate items (R4-AC3).
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, Field

from psychtool.core.spans import Span, verify_quote_in
from psychtool.core.workspace import Material

# Prototype buildCase sentence splitter originally used
# ``[^.!?。！？]+[.!?。！？]?``; PT-06 keeps that shape but a "." no longer
# ends a sentence inside abbreviations ("a.m", "1.5", "e.g") — see
# ``_is_sentence_end``. "!" / "?" / "。" / "！" / "？" always end a sentence.
_TERMINATORS = ".!?。！？"


# A "." does NOT end a sentence right before a non-whitespace character
# ("a.m", "1.5", "e.g") nor after a known abbreviation (case-insensitive);
# "!", "?", "。", "！", "？" always end a sentence.
_KNOWN_ABBREVIATIONS = frozenset(
    {"a.m", "p.m", "mr", "mrs", "ms", "dr", "e.g", "i.e", "etc", "vs", "approx"}
)


def _is_sentence_end(text: str, dot_index: int) -> bool:
    """True when the "." at ``dot_index`` really ends a sentence.

    Scans backwards from the dot without copying the whole prefix — only the
    word immediately before the dot matters (at most ~10 chars/dots), so this
    stays O(1) per "." instead of O(len(text)).
    """
    if dot_index + 1 < len(text) and not text[dot_index + 1].isspace():
        return False
    index = dot_index
    # Skip whitespace immediately before the dot.
    while index > 0 and text[index - 1].isspace():
        index -= 1
    # Collect the word before the dot, at most a few characters.
    chars: list[str] = []
    while index > 0 and len(chars) < 10:
        char = text[index - 1]
        if char.isalnum() or char == ".":
            chars.append(char)
            index -= 1
        else:
            break
    word = "".join(reversed(chars)).lower().strip(".")
    return word not in _KNOWN_ABBREVIATIONS


def _sentence_chunks(text: str) -> list[str]:
    """Chunks split at real sentence ends (each terminator included)."""
    chunks: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char == ".":
            if not _is_sentence_end(text, index):
                continue
        elif char not in "!?。！？":
            continue
        chunks.append(text[start : index + 1])
        start = index + 1
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _min_length(text: str) -> int:
    # CJK carries more per character: shorter Chinese quotes stay checkable.
    return 4 if _has_cjk(text) else 6


class EvidenceCandidate(BaseModel):
    """One checkable sentence from one passage, with its verbatim span."""

    id: str
    quote: str
    span: Span
    paragraph: int = Field(ge=1)  # 1-based passage position in the material


class Extractor(Protocol):
    """The extractor seam: implementations turn a material into candidates.

    M1 ships only :class:`RuleExtractor` (local rules, no model). An
    LLMExtractor is explicitly out of scope (PT-16).
    """

    name: str

    def extract(self, material: Material) -> list[EvidenceCandidate]: ...


class RuleExtractor:
    """Prototype heuristic: per passage, split into sentences, keep long ones.

    For each sentence: trim surrounding whitespace, strip ONE trailing
    sentence terminator, skip quotes shorter than 6 characters (4 when the
    quote contains CJK characters), and locate the sentence inside the
    passage by searching forward from the previous sentence's end so repeated
    sentences get distinct spans. Ids are deterministic:
    ``{material.id}-v{version}-{passage.id}-s{n}`` with ``n`` the 1-based
    kept-sentence index within the passage.
    """

    name = "rule"

    def extract(self, material: Material) -> list[EvidenceCandidate]:
        candidates: list[EvidenceCandidate] = []
        for paragraph, passage in enumerate(material.passages, start=1):
            sentence_number = 0
            search_from = 0
            for chunk in _sentence_chunks(passage.text):
                sentence = chunk.strip()
                if sentence and sentence[-1] in _TERMINATORS:
                    sentence = sentence[:-1].rstrip()
                if len(sentence) < _min_length(sentence):
                    continue
                relative = passage.text.find(sentence, search_from)
                if relative < 0:  # pragma: no cover - chunks come from the text
                    relative = passage.text.find(sentence)
                if relative < 0:  # pragma: no cover
                    continue
                # ``paragraph`` is the 1-based passage position; the id embeds
                # the 1-based *kept-sentence* index (n in ...-s{n}).
                sentence_number += 1
                start = relative
                end = relative + len(sentence)
                search_from = end
                candidates.append(
                    EvidenceCandidate(
                        id=f"{material.id}-v{material.version}-{passage.id}-s{sentence_number}",
                        quote=sentence,
                        span=Span(
                            material_id=material.id,
                            material_version=material.version,
                            passage_id=passage.id,
                            start=start,
                            end=end,
                        ),
                        paragraph=paragraph,
                    )
                )
        return candidates


class EvidenceResult(BaseModel):
    """Verified evidence items plus the count of dropped candidates."""

    items: list[EvidenceCandidate]
    dropped: int = Field(ge=0)


def extract_evidence(extractor: Extractor, materials: list[Material]) -> EvidenceResult:
    """Run one extractor over the materials and keep only verbatim matches.

    A candidate whose quote is not exactly ``passage.text[start:end]`` for
    its own material version is dropped silently except for the count; quotes
    are never repaired. Candidates are never merged or de-duplicated, so
    identical or contradictory sentences across passages/materials each stay
    as their own item (R4-AC3).
    """
    items: list[EvidenceCandidate] = []
    dropped = 0
    for material in materials:
        # Build the passage index once per material instead of rescanning
        # material.passages for every candidate (R4 scale guard).
        passages_by_id = {passage.id: passage.text for passage in material.passages}
        for candidate in extractor.extract(material):
            if verify_quote_in(passages_by_id, material, candidate.span, candidate.quote):
                items.append(candidate)
            else:
                dropped += 1
    return EvidenceResult(items=items, dropped=dropped)
