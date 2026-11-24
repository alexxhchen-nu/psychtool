"""PT-06: Span contract — code-point offsets, verbatim slicing, no repair."""

from __future__ import annotations

import pytest

from psychtool.core.spans import Span, span_text, verify_quote
from psychtool.core.workspace import Material, Passage


def _material(passage_text: str = "Mother says he sleeps about 8 hours a night.",
              *, material_id: str = "doc-1", version: int = 1,
              passage_id: str = "p001") -> Material:
    return Material(
        id=material_id,
        case_id="case-a",
        version=version,
        title="Synthetic note",
        provider="synthetic",
        date="2026-11-24",
        passages=[Passage(id=passage_id, text=passage_text)],
    )


def _span(material: Material, start: int, end: int,
          passage_id: str | None = None) -> Span:
    return Span(
        material_id=material.id,
        material_version=material.version,
        passage_id=passage_id or material.passages[0].id,
        start=start,
        end=end,
    )


TEXT = "Mother says he sleeps about 8 hours a night."


def test_verbatim_true_case():
    material = _material(TEXT)
    quote = TEXT[7:31]
    assert verify_quote(material, _span(material, 7, 31), quote) is True
    assert span_text(material, _span(material, 7, 31)) == quote


def test_verbatim_false_when_quote_off_by_one():
    material = _material(TEXT)
    span = _span(material, 7, 31)
    assert verify_quote(material, span, TEXT[8:31]) is False  # shifted start
    assert verify_quote(material, span, TEXT[7:32]) is False  # shifted end


def test_empty_quote_is_false():
    material = _material(TEXT)
    assert verify_quote(material, _span(material, 7, 31), "") is False


def test_span_construction_rejects_negative_offsets_and_empty_range():
    # Spec: Span construction rejects start >= end and negative offsets.
    with pytest.raises(ValueError):
        _span(_material(TEXT), 3, 3)  # empty range
    with pytest.raises(ValueError):
        _span(_material(TEXT), 3, 2)  # inverted range
    with pytest.raises(ValueError):
        Span(material_id="d", material_version=1, passage_id="p", start=-1, end=5)


@pytest.mark.parametrize(
    "start,end",
    [
        (0, len(TEXT) + 1),  # end past the text
        (len(TEXT), len(TEXT) + 1),  # start past the text
    ],
)
def test_bad_bounds_are_false(start, end):
    material = _material(TEXT)
    span = Span(
        material_id=material.id,
        material_version=material.version,
        passage_id="p001",
        start=start,
        end=end,
    )
    # verify_quote never raises: out-of-range end, wrong id/version,
    # unknown passage and empty quote are all False.
    assert verify_quote(material, span, "x" * (end - start)) is False
    with pytest.raises(IndexError):
        span_text(material, span)


def test_wrong_material_id_and_version():
    material = _material(TEXT, version=2)
    quote = TEXT[0:10]
    other_id = _span(material, 0, 10)
    other_id.material_id = "doc-2"
    assert verify_quote(material, other_id, quote) is False
    other_version = _span(material, 0, 10)
    other_version.material_version = 1
    assert verify_quote(material, other_version, quote) is False


def test_unknown_passage():
    material = _material(TEXT)
    span = _span(material, 0, 10, passage_id="p999")
    assert verify_quote(material, span, TEXT[0:10]) is False
    with pytest.raises(ValueError):
        span_text(material, span)


def test_span_text_raises_on_mismatch():
    material = _material(TEXT)
    span = _span(material, 0, 10)
    span.material_id = "doc-2"
    with pytest.raises(ValueError):
        span_text(material, span)


def test_astral_character_offsets_are_code_points():
    text = "😀 He sleeps about 7 hours a night."
    material = _material(text)
    quote = "He sleeps about 7 hours"
    start = text.index("He")
    end = start + len(quote)
    # Python string indexing is by code point; the emoji must not shift the
    # offsets (UTF-16-based clients must use Array.from to agree).
    assert start == 2
    assert verify_quote(material, _span(material, start, end), quote) is True
    assert verify_quote(material, _span(material, start - 1, end), quote) is False


def test_cjk_offsets_are_code_points():
    text = "他经常熬夜到凌晨一点。周末会补觉。"
    material = _material(text)
    quote = "他经常熬夜到凌晨一点"
    start = 0
    end = len(quote)
    assert verify_quote(material, _span(material, start, end), quote) is True


def test_span_model_validates_field_shape():
    with pytest.raises(ValueError):
        Span(material_id="d", material_version=0, passage_id="p", start=0, end=1)
    with pytest.raises(ValueError):
        Span(material_id="d", material_version=1, passage_id="p", start=-1, end=1)
