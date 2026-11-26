"""Sentence-level citation checking and draft wording filters (PT-12 / GROK-42).

A draft is a sequence of sentences. Every sentence either cites persisted
evidence (the sentence contains a verbatim slice of an active evidence quote)
or does not. Citation checking is deterministic and read-only: it maps draft
text to sentence records, computes their sourced/state, and never rewrites,
auto-corrects or repairs the text.

The draft wording filters are the R7 guard. A Summary draft may not carry
diagnostic or recommendation wording; every other non-clinician draft may not
carry diagnostic wording or manual text (criterion/DSM/ICD fragments) that is
not a verbatim substring of something she uploaded. A clinician-authored
section is never filtered. The fixed "this is not a diagnosis" disclaimer
shown on every dimension view is never a violation.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterable, Literal, Sequence

from pydantic import BaseModel, Field

from psychtool.core.dimensions import (
    DIAGNOSIS_PHRASES,
    _BLOCKED_NAME_TOKENS,
    _CRITERION_PATTERNS,
)
from psychtool.core.extract import (
    _TERMINATORS,
    _has_cjk,
    _min_length,
    _sentence_chunks,
)

SentenceState = Literal["needs_review", "verified", "unverified", "my_judgment"]
VALID_SENTENCE_STATES = frozenset(
    {"needs_review", "verified", "unverified", "my_judgment"}
)

# The one fixed disclaimer every dimension view shows. It is a sentence the
# system itself renders, never a violation in a draft (R7-AC6).
DISCLAIMER_PHRASE = "this is not a diagnosis"

# Diagnostic phrases carried over from dimensions.py, minus the disclaimer.
DRAFT_DIAGNOSIS_PHRASES: tuple[str, ...] = tuple(
    phrase for phrase in DIAGNOSIS_PHRASES if phrase != DISCLAIMER_PHRASE
)

# Recommendation wording, used ONLY by the Summary guard. Literal, short,
# case-insensitive, and deliberately a fixed list — not a semantic detector.
RECOMMENDATION_PHRASES: tuple[str, ...] = (
    "i recommend",
    "it is recommended",
    "recommend that",
    "recommendation is",
    "should be treated",
    "treatment plan",
)

SUMMARY_DRAFT_REASON = "a Summary draft must not contain diagnostic or recommendation wording"
DRAFT_FILTER_REASON = "draft text must not contain diagnostic wording or un-uploaded manual text"

# The default-template clinician-authored section ids. The core save path uses
# the loaded template's content types; the citecheck route only receives a
# section id, so it relies on this fixed mapping.
CLINICIAN_AUTHORED_SECTION_IDS = frozenset({"clinical_impressions", "recommendations"})


class DraftFilterBlockedError(ValueError):
    """Raised when a draft trips the R7 wording filter.

    The message is one of the fixed reason strings above; the API turns it into
    a fixed 400 body. No draft text, phrase match, claim id or exception text is
    ever echoed back to the client or logged.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class SentenceEvidence(BaseModel):
    """One active evidence row available to a citation check."""

    evidence_id: str
    quote: str


class DraftSentence(BaseModel):
    """One sentence of a draft, with the citations and state we computed.

    ``state`` on input is never trusted for an unsourced sentence: citation
    checking recomputes it. ``sentence_id`` and ``ordinal`` are also
    recomputed from the section id, the position and the text.
    """

    sentence_id: str
    ordinal: int = Field(ge=1)
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    state: str = "needs_review"


class CiteCheckResult(BaseModel):
    """The read-only outcome of checking one draft."""

    sentences: list[DraftSentence] = Field(default_factory=list)
    blocked: bool = False
    detail: str | None = None
    text: str = ""


def make_sentence_id(section_id: str, ordinal: int, text: str) -> str:
    """Deterministic id: ``sent_`` + first 24 hex of sha256(section/ordinal/text)."""
    payload = section_id + "\x1f" + str(ordinal) + "\x1f" + text
    return "sent_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def split_draft_sentences(text: str) -> list[str]:
    """Split draft text into sentences, reusing the extractor's splitter."""
    chunks = [chunk.strip() for chunk in _sentence_chunks(text)]
    return [chunk for chunk in chunks if chunk]


def is_summary_section(section_id: str, title: str | None = None) -> bool:
    """True when a section is the Summary section (id or title, case-insensitive)."""
    if section_id == "summary":
        return True
    return bool(title) and title.strip().casefold() == "summary"


def is_clinician_authored_section_id(section_id: str) -> bool:
    return section_id in CLINICIAN_AUTHORED_SECTION_IDS


def _normalize_for_match(text: str) -> str:
    """Casefold, collapse whitespace, strip one trailing sentence terminator."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if collapsed and collapsed[-1] in _TERMINATORS:
        collapsed = collapsed[:-1].rstrip()
    return collapsed.casefold()


def _quotes_overlap(sentence: str, quote: str) -> bool:
    """True when one normalized side contains the other with enough overlap."""
    left = _normalize_for_match(sentence)
    right = _normalize_for_match(quote)
    if not left or not right:
        return False
    if right in left:
        fragment = right
    elif left in right:
        fragment = left
    else:
        return False
    return len(fragment) >= _min_length(fragment)


def _as_evidence(item: SentenceEvidence | dict) -> SentenceEvidence:
    if isinstance(item, SentenceEvidence):
        return item
    if isinstance(item, dict):
        evidence_id = item.get("evidence_id", item.get("id"))
        return SentenceEvidence(evidence_id=evidence_id or "", quote=item.get("quote", ""))
    raise TypeError("unsupported evidence input")


def _dedupe(values: Iterable[str]) -> list[str]:
    """Stable de-duplication, order preserved."""
    return list(dict.fromkeys(values))


def _find_existing(
    existing: Sequence[DraftSentence], sentence_id: str, ordinal: int, text: str
) -> DraftSentence | None:
    for sentence in existing:
        if sentence.sentence_id == sentence_id:
            return sentence
    for sentence in existing:
        if sentence.ordinal == ordinal and sentence.text == text:
            return sentence
    return None


def _compute_state(
    existing: Sequence[DraftSentence],
    sentence_id: str,
    ordinal: int,
    text: str,
    evidence_ids: list[str],
    caller_state: str,
) -> SentenceState:
    """Recompute one sentence's state; caller-provided state is never trusted.

    - ``my_judgment`` (existing, or explicitly supplied) is always preserved.
    - a sourced sentence defaults to ``needs_review``; ``verified`` is kept only
      when a matching existing sentence was verified and its evidence ids are
      still a subset of the new ones.
    - an unsourced sentence that is not ``my_judgment`` is ``unverified``.
    """
    found = _find_existing(existing, sentence_id, ordinal, text)
    existing_state = found.state if found else None
    existing_evidence = list(found.evidence_ids) if found else []
    if existing_state == "my_judgment" or caller_state == "my_judgment":
        return "my_judgment"
    if evidence_ids:
        if existing_state == "verified" and set(existing_evidence) <= set(evidence_ids):
            return "verified"
        return "needs_review"
    return "unverified"


def _build_from_text(
    section_id: str, text: str, evidence: Sequence[SentenceEvidence]
) -> list[DraftSentence]:
    built: list[DraftSentence] = []
    for ordinal, chunk in enumerate(split_draft_sentences(text), start=1):
        sentence_id = make_sentence_id(section_id, ordinal, chunk)
        matched = _dedupe(
            item.evidence_id for item in evidence if _quotes_overlap(chunk, item.quote)
        )
        built.append(
            DraftSentence(
                sentence_id=sentence_id,
                ordinal=ordinal,
                text=chunk,
                evidence_ids=matched,
            )
        )
    return built


def _canonicalize(
    section_id: str,
    text: str,
    sentences: Sequence[DraftSentence],
    known_evidence_ids: set[str],
    existing: Sequence[DraftSentence],
    strict_evidence: bool,
) -> list[DraftSentence]:
    built: list[DraftSentence] = []
    for ordinal, supplied in enumerate(sentences, start=1):
        chunk = (supplied.text or "").strip()
        if not chunk:
            raise ValueError("sentence text must not be empty")
        sentence_id = make_sentence_id(section_id, ordinal, chunk)
        ordered = _dedupe(supplied.evidence_ids)
        if strict_evidence:
            missing = [eid for eid in ordered if eid not in known_evidence_ids]
            if missing:
                raise ValueError(f"unknown evidence id for this case: {missing[0]!r}")
            evidence_ids = ordered
        else:
            evidence_ids = [eid for eid in ordered if eid in known_evidence_ids]
        built.append(
            DraftSentence(
                sentence_id=sentence_id,
                ordinal=ordinal,
                text=chunk,
                evidence_ids=evidence_ids,
                state=supplied.state,
            )
        )
    for sentence in built:
        sentence.state = _compute_state(
            existing, sentence.sentence_id, sentence.ordinal, sentence.text,
            sentence.evidence_ids, sentence.state,
        )
    return built


def _diagnostic_fragment(text: str, uploaded_texts: Sequence[str]) -> str | None:
    """First disallowed diagnostic or manual fragment, or None when clean.

    Diagnostic phrases (minus the fixed disclaimer) are always refused. A
    criterion/DSM/ICD fragment is refused unless it is an exact verbatim
    substring of an uploaded text (R7-AC8).
    """
    lowered = text.casefold()
    for phrase in DRAFT_DIAGNOSIS_PHRASES:
        index = lowered.find(phrase)
        if index >= 0:
            return text[index : index + len(phrase)]
    for pattern in (*_CRITERION_PATTERNS, *_BLOCKED_NAME_TOKENS):
        match = pattern.search(text)
        if match is not None:
            fragment = match.group(0)
            if not any(fragment in uploaded for uploaded in uploaded_texts):
                return fragment
    return None


def _recommendation_fragment(text: str) -> str | None:
    lowered = text.casefold()
    for phrase in RECOMMENDATION_PHRASES:
        index = lowered.find(phrase)
        if index >= 0:
            return text[index : index + len(phrase)]
    return None


def check_draft_text(
    section_id: str,
    text: str,
    uploaded_texts: Sequence[str] = (),
    *,
    clinician_authored: bool = False,
    title: str | None = None,
) -> str | None:
    """Return the fixed block reason for a draft, or None when it may be saved."""
    if clinician_authored:
        return None
    diagnostic = _diagnostic_fragment(text, uploaded_texts)
    if is_summary_section(section_id, title):
        if diagnostic is not None or _recommendation_fragment(text) is not None:
            return SUMMARY_DRAFT_REASON
        return None
    if diagnostic is not None:
        return DRAFT_FILTER_REASON
    return None


def citecheck_text(
    *,
    section_id: str,
    text: str,
    evidence: Sequence[SentenceEvidence | dict] = (),
    existing_sentences: Sequence[DraftSentence] = (),
    uploaded_texts: Sequence[str] = (),
    sentences: Sequence[DraftSentence] | None = None,
    clinician_authored: bool | None = None,
    title: str | None = None,
    strict_evidence: bool = False,
    known_evidence_ids: Sequence[str] | None = None,
) -> CiteCheckResult:
    """Check one draft without writing anything.

    When ``sentences`` is omitted the text is split and every sentence is matched
    against the supplied active evidence. When ``sentences`` is supplied they are
    canonicalized (recomputed ids/ordinals, validated evidence ids, recomputed
    states). The result carries the canonical text, the sentences and the wording
    filter outcome.

    ``known_evidence_ids`` lets a caller validate citations against every
    persisted evidence id (including superseded rows), while matching still only
    uses the ``evidence`` sequence it passed in.
    """
    evidence_list = [_as_evidence(item) for item in evidence]
    known_ids = (
        set(known_evidence_ids)
        if known_evidence_ids is not None
        else {item.evidence_id for item in evidence_list}
    )
    if clinician_authored is None:
        clinician_authored = is_clinician_authored_section_id(section_id)
    existing = list(existing_sentences)

    if sentences is None:
        built = _build_from_text(section_id, text, evidence_list)
    else:
        built = _canonicalize(
            section_id, text, sentences, known_ids, existing, strict_evidence
        )
    for sentence in built:
        sentence.state = _compute_state(
            existing, sentence.sentence_id, sentence.ordinal, sentence.text,
            sentence.evidence_ids, sentence.state,
        )

    # Drafts are never auto-rewritten (ADR 0021). Sentence records annotate
    # the caller's text; the body is returned unchanged even when it was
    # split or joined differently than a single-space concatenation.
    reason = check_draft_text(
        section_id,
        text,
        uploaded_texts,
        clinician_authored=clinician_authored,
        title=title,
    )
    return CiteCheckResult(
        text=text,
        sentences=built,
        blocked=reason is not None,
        detail=reason,
    )


__all__ = [
    "DISCLAIMER_PHRASE",
    "DRAFT_DIAGNOSIS_PHRASES",
    "DRAFT_FILTER_REASON",
    "RECOMMENDATION_PHRASES",
    "SUMMARY_DRAFT_REASON",
    "VALID_SENTENCE_STATES",
    "CiteCheckResult",
    "DraftFilterBlockedError",
    "DraftSentence",
    "SentenceEvidence",
    "SentenceState",
    "check_draft_text",
    "citecheck_text",
    "is_clinician_authored_section_id",
    "is_summary_section",
    "make_sentence_id",
    "split_draft_sentences",
]
