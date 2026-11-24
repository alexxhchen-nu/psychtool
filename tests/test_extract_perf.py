"""Performance guard: extract_evidence must stay linear, not quadratic.

Two historical hotspots are covered here:
- ``spans._find_passage`` used to rescan ``material.passages`` for every
  candidate (passages × candidates);
- ``extract._is_sentence_end`` used to copy ``text[:dot_index]`` for every
  "." (quadratic inside one long passage).

Each run is asserted under a generous 5-second budget to avoid flakiness.
"""

from __future__ import annotations

import time

from psychtool.core.extract import RuleExtractor, extract_evidence
from psychtool.core.workspace import Material, Passage

_EXTRACTOR = RuleExtractor()


def _material(passages: list[Passage], material_id: str = "perf") -> Material:
    return Material(
        id=material_id,
        case_id="perf-case",
        version=1,
        title="perf",
        provider="perf",
        date="2026-11-24",
        passages=passages,
    )


def _many_passages(count: int) -> Material:
    # Each short paragraph keeps "Dr." and "7.5" — the abbreviation/decimal
    # dots that used to cost a full prefix copy each.
    return _material(
        [
            Passage(id=f"p{i:05d}", text=f"Dr. Lee notes 7.5 hours for record {i}.")
            for i in range(count)
        ]
    )


def _one_big_passage(target_bytes: int) -> Material:
    unit = "Dr. Lee notes 7.5 hours before bed. "
    repeats = target_bytes // len(unit)
    return _material(
        [Passage(id="p00000", text=unit * repeats)],
    )


def test_extract_evidence_is_linear_on_many_passages() -> None:
    result = extract_evidence(_EXTRACTOR, [_many_passages(50_000)])
    assert result.dropped == 0
    assert len(result.items) == 50_000


def test_extract_evidence_is_linear_on_one_large_passage() -> None:
    material = _one_big_passage(2 * 1024 * 1024)
    assert len(material.passages[0].text.encode("utf-8")) <= 2 * 1024 * 1024 + len(
        "Dr. Lee notes 7.5 hours before bed. "
    )
    result = extract_evidence(_EXTRACTOR, [material])
    assert result.dropped == 0
    assert len(result.items) > 10_000


def test_extract_evidence_large_inputs_finish_quickly() -> None:
    start = time.perf_counter()
    extract_evidence(_EXTRACTOR, [_many_passages(50_000)])
    extract_evidence(_EXTRACTOR, [_one_big_passage(2 * 1024 * 1024)])
    elapsed = time.perf_counter() - start
    assert elapsed < 5, f"extract_evidence was too slow: {elapsed:.2f}s"


def test_extract_evidence_output_matches_small_sample() -> None:
    """The R4 semantic contract must be unchanged by the performance fixes."""
    material = _material(
        [
            Passage(id="p0", text="Mother says he sleeps about 8 hours a night."),
            Passage(id="p1", text="He walked 7.5 miles to school with Dr. Lee."),
            Passage(id="p2", text="He stays up until 1 a.m. most nights."),
        ]
    )
    result = extract_evidence(_EXTRACTOR, [material])
    assert result.dropped == 0
    quotes = [(item.quote, item.span.passage_id, item.span.start, item.span.end) for item in result.items]
    assert quotes == [
        ("Mother says he sleeps about 8 hours a night", "p0", 0, 43),
        ("He walked 7.5 miles to school with Dr. Lee", "p1", 0, 42),
        ("He stays up until 1 a.m. most nights", "p2", 0, 36),
    ]
    for item in result.items:
        passage = next(p for p in material.passages if p.id == item.span.passage_id)
        assert passage.text[item.span.start : item.span.end] == item.quote
