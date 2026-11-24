"""PT-06: RuleExtractor heuristic, verbatim filter, no-merging (R4-AC3)."""

from __future__ import annotations

import pytest

from psychtool.core.extract import (
    EvidenceCandidate,
    Extractor,
    RuleExtractor,
    extract_evidence,
)
from psychtool.core.spans import Span, verify_quote
from psychtool.core.workspace import Material, Passage


def _material(*passage_texts: str, material_id: str = "doc-1", version: int = 1,
              case_id: str = "case-a") -> Material:
    return Material(
        id=material_id,
        case_id=case_id,
        version=version,
        title=f"Title of {material_id}",
        provider="synthetic",
        date="2026-11-24",
        passages=[Passage(id=f"p{i:03d}", text=t) for i, t in enumerate(passage_texts, 1)],
    )


# -- RuleExtractor: sentence splitting ---------------------------------------


def test_sentence_splitting_english():
    material = _material(
        "Mother says he sleeps about 8 hours a night and keeps a regular "
        "routine. He walks to school with a neighbour."
    )
    candidates = RuleExtractor().extract(material)
    assert [c.quote for c in candidates] == [
        "Mother says he sleeps about 8 hours a night and keeps a regular routine",
        "He walks to school with a neighbour",
    ]
    assert [c.paragraph for c in candidates] == [1, 1]


def test_sentence_splitting_chinese_terminators():
    material = _material("他经常熬夜到凌晨。周末会补觉！整体情况还行。")
    candidates = RuleExtractor().extract(material)
    assert [c.quote for c in candidates] == [
        "他经常熬夜到凌晨",
        "周末会补觉",
        "整体情况还行",
    ]


def test_sentence_splitting_abbreviations_do_not_break_sentences():
    # "a.m." inside the sentence must not split it (only the final "." is
    # stripped; the internal "a.m." stays in the quote).
    material = _material(
        "I often stay on my phone until about 1 a.m. before falling asleep."
    )
    (candidate,) = RuleExtractor().extract(material)
    assert candidate.quote == (
        "I often stay on my phone until about 1 a.m. before falling asleep"
    )
    assert "a.m." in candidate.quote
    assert candidate.span.start == 0


def test_sentence_splitting_dr_abbreviation():
    material = _material("Dr. Lee saw him.")
    (candidate,) = RuleExtractor().extract(material)
    assert candidate.quote == "Dr. Lee saw him"


def test_sentence_splitting_decimal_number():
    material = _material("He slept 7.5 hours.")
    (candidate,) = RuleExtractor().extract(material)
    assert candidate.quote == "He slept 7.5 hours"


def test_short_chinese_quote_kept_with_lower_minimum():
    # CJK minimum is 4 characters, so the 5-char "周末会补觉" is kept.
    material = _material("他经常熬夜到凌晨。周末会补觉。")
    candidates = RuleExtractor().extract(material)
    assert [c.quote for c in candidates] == ["他经常熬夜到凌晨", "周末会补觉"]


def test_trailing_terminator_stripped_but_not_inner_punctuation():
    material = _material("He sleeps about 8 hours a night!")
    (candidate,) = RuleExtractor().extract(material)
    assert candidate.quote == "He sleeps about 8 hours a night"


def test_quotes_shorter_than_six_characters_skipped():
    material = _material("OK. Yes! This sentence is definitely long enough.")
    candidates = RuleExtractor().extract(material)
    assert [c.quote for c in candidates] == ["This sentence is definitely long enough"]


def test_repeated_sentence_gets_distinct_spans():
    material = _material("He sleeps well. He sleeps well.")
    candidates = RuleExtractor().extract(material)
    assert len(candidates) == 2
    assert candidates[0].quote == candidates[1].quote == "He sleeps well"
    assert candidates[0].span.start != candidates[1].span.start
    assert candidates[1].span.start > candidates[0].span.start


def test_every_candidate_verifies_against_its_source():
    material = _material(
        "Mother says he sleeps about 8 hours a night. He walks to school.",
        "I often stay on my phone until about 1 a.m. before falling asleep.",
    )
    candidates = RuleExtractor().extract(material)
    assert candidates
    for candidate in candidates:
        assert verify_quote(material, candidate.span, candidate.quote) is True
    # Offsets address the passage of the candidate's paragraph.
    assert candidates[0].paragraph == 1
    assert candidates[-1].paragraph == 2


def test_deterministic_ids():
    material = _material("Mother says he sleeps about 8 hours a night.")
    first = RuleExtractor().extract(material)
    second = RuleExtractor().extract(material)
    assert [c.id for c in first] == [c.id for c in second]
    assert first[0].id == "doc-1-v1-p001-s1"


def test_ids_encode_material_version_and_sentence_index():
    material = _material(
        "He walks to school with a neighbour. She packs his lunch.",
        version=3,
    )
    candidates = RuleExtractor().extract(material)
    assert [c.id for c in candidates] == ["doc-1-v3-p001-s1", "doc-1-v3-p001-s2"]


def test_extractor_protocol_shape():
    extractor: Extractor = RuleExtractor()
    assert extractor.name == "rule"


# -- extract_evidence: verbatim filter, no merging ----------------------------


class _FakeExtractor:
    """Returns scripted candidates regardless of material."""

    name = "fake"

    def __init__(self, candidates: list[EvidenceCandidate]) -> None:
        self._candidates = candidates

    def extract(self, material: Material) -> list[EvidenceCandidate]:
        return list(self._candidates)


def _candidate(material: Material, quote: str, start: int, end: int) -> EvidenceCandidate:
    return EvidenceCandidate(
        id=f"{material.id}-{start}",
        quote=quote,
        span=Span(
            material_id=material.id,
            material_version=material.version,
            passage_id=material.passages[0].id,
            start=start,
            end=end,
        ),
        paragraph=1,
    )


def test_bad_span_is_dropped_and_counted():
    text = "Mother says he sleeps about 8 hours a night."
    material = _material(text)
    good = _candidate(material, text[7:31], 7, 31)
    # Quote off by one character / wrong offsets:
    bad = _candidate(material, text[7:31], 8, 31)
    result = extract_evidence(_FakeExtractor([good, bad]), [material])
    assert [item.quote for item in result.items] == [text[7:31]]
    assert result.dropped == 1


def test_identical_sentence_in_two_materials_stays_two_items():
    text = "Mother says he sleeps about 8 hours a night."
    caregiver = _material(text, material_id="caregiver", version=1)
    teacher = _material(text, material_id="teacher", version=1)
    extractor = RuleExtractor()
    result = extract_evidence(extractor, [caregiver, teacher])
    assert len(result.items) == 2
    assert result.dropped == 0
    by_material = {item.span.material_id for item in result.items}
    assert by_material == {"caregiver", "teacher"}
    assert all(item.quote == text[:-1] for item in result.items)


def test_r4_ac3_conflicting_sleep_accounts_both_kept():
    caregiver = _material(
        "Mother says he sleeps about 8 hours a night and keeps a regular "
        "routine.",
        material_id="caregiver",
    )
    self_report = _material(
        "I often stay on my phone until about 1 a.m. before falling asleep.",
        material_id="self",
    )
    result = extract_evidence(RuleExtractor(), [caregiver, self_report])
    assert result.dropped == 0
    assert len(result.items) == 2
    quotes = {item.span.material_id: item.quote for item in result.items}
    assert "8 hours" in quotes["caregiver"]
    assert "1 a.m." in quotes["self"]
    for item in result.items:
        source = caregiver if item.span.material_id == "caregiver" else self_report
        assert verify_quote(source, item.span, item.quote) is True
