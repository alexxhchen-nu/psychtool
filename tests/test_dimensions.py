"""PT-08 (GROK-38) unit tests for psychtool/core/dimensions.py.

Covers: name parsing (prototype list of 6 names + intro line skipped,
names are verbatim substrings of their lines), matcher branches (one hit,
two or more -> no dimension, none, no list), CJK bigrams, the synonym
table only matching HER names, reason length <= 140 with a verbatim hit,
and the four hard rules — each with a test that would fail if the rule
were removed.
"""

from __future__ import annotations

import re

import pytest

from psychtool.core.dimensions import (
    DIM_RULES_VERSION,
    NO_HIT_REASON,
    NO_LIST_REASON,
    SAFE_REASON,
    STALE_CHOICE_REASON,
    Dimension,
    DimensionSuggestion,
    apply_hard_rules,
    dim_hit,
    find_blocked_citation,
    is_safe_dimension_name,
    is_safe_reason,
    match_dimensions,
    one_hit_reason,
    parse_dimension_line,
    two_hit_reason,
)

# The prototype's synthetic dimension list (intro line + 6 names).
PROTOTYPE_LIST = (
    "This is a clinician-made working list of the working areas we track "
    "for this practice, not any official criteria or diagnostic text.\n"
    "Dimension 1: Attention\n"
    "Dimension 2: Reading and decoding\n"
    "Dimension 3: Sleep and routine\n"
    "Dimension 4: Social interaction\n"
    "Dimension 5: Mood and emotion\n"
    "Dimension 6: Memory and processing speed"
)


def _parse_list(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        name = parse_dimension_line(line)
        if name:
            names.append(name)
    return names


# -- name parsing -------------------------------------------------------------


def test_parse_prototype_list_yields_six_names_and_skips_intro():
    names = _parse_list(PROTOTYPE_LIST)
    assert names == [
        "Attention",
        "Reading and decoding",
        "Sleep and routine",
        "Social interaction",
        "Mood and emotion",
        "Memory and processing speed",
    ]


def test_parse_names_are_verbatim_substrings_of_their_lines():
    lines = PROTOTYPE_LIST.splitlines()
    names = _parse_list(PROTOTYPE_LIST)
    remaining = list(lines)
    for name in names:
        found = any(name in line for line in remaining)
        assert found, f"{name!r} is not a verbatim substring of any list line"


def test_parse_strips_label_parenthetical_and_trailing_period():
    assert parse_dimension_line("Dimension 3: Sleep (caregiver report).") == "Sleep"
    assert parse_dimension_line("维度二：阅读（家长报告）。") == "阅读"
    assert parse_dimension_line("维度2: Sleep and routine") == "Sleep and routine"


def test_parse_chinese_numeral_label():
    assert parse_dimension_line("维度三：睡眠作息") == "睡眠作息"


def test_parse_intro_sentence_is_not_a_dimension():
    line = (
        "This is a clinician-made working list of the working areas we "
        "track for this practice, not any official criteria."
    )
    assert parse_dimension_line(line) is None


def test_parse_short_or_overlong_names_rejected():
    assert parse_dimension_line("Dimension 1: X") is None
    long_name = " word" * 30  # 30 words -> >= 12 words
    assert parse_dimension_line(f"Dimension 1: {long_name}") is None
    too_long = "a" * 81
    assert parse_dimension_line(f"Dimension 1: {too_long}") is None


# -- matcher branches ----------------------------------------------------------

DIMS = [
    Dimension("dim_a1" + "0" * 20, "Attention"),
    Dimension("dim_b1" + "0" * 20, "Reading and decoding"),
    Dimension("dim_c1" + "0" * 20, "Sleep and routine"),
]


def test_matcher_exactly_one_hit_assigns_that_dimension():
    suggestion = match_dimensions(
        "She is easily distractible during homework.", DIMS
    )
    assert suggestion.dimension_id == DIMS[0].id
    assert suggestion.state == "needs_review"
    assert "distractible" in suggestion.reason
    assert "Attention" in suggestion.reason


def test_matcher_two_hits_assigns_no_dimension():
    suggestion = match_dimensions(
        "He reads slowly and cannot focus in class.", DIMS
    )
    # Both "Reading and decoding" (reads) and "Attention" (focus) hit.
    assert suggestion.dimension_id is None
    assert suggestion.state == "needs_review"
    assert "Reading and decoding" in suggestion.reason
    assert "Attention" in suggestion.reason
    assert "cannot tell" in suggestion.reason


def test_matcher_no_hit_assigns_none():
    suggestion = match_dimensions(
        "The family moved here two years ago.", DIMS
    )
    assert suggestion.dimension_id is None
    assert suggestion.state == "none"
    assert suggestion.reason == NO_HIT_REASON


def test_matcher_no_list_assigns_none_with_fixed_reason():
    suggestion = match_dimensions("anything at all", None)
    assert suggestion.dimension_id is None
    assert suggestion.state == "none"
    assert suggestion.reason == NO_LIST_REASON
    suggestion = match_dimensions("anything at all", [])
    assert suggestion.reason == NO_LIST_REASON


def test_matcher_cjk_bigram_hit():
    dims = [Dimension("dim_d1" + "0" * 20, "注意力")]
    suggestion = match_dimensions("上课时注意力不集中，经常走神。", dims)
    assert suggestion.dimension_id == dims[0].id
    assert "注意" in suggestion.reason


def test_matcher_cjk_name_without_matching_bigram_stops():
    # CJK names do not fall through to the Latin/synonym checks.
    dims = [Dimension("dim_e1" + "0" * 20, "注意力")]
    suggestion = match_dimensions("He reads slowly and sleeps well.", dims)
    assert suggestion.dimension_id is None
    assert suggestion.state == "none"


def test_synonyms_only_match_her_names_never_create_them():
    # "focus" appears in the quote and the synonym table maps it, but if
    # her list does not contain a matching name, no dimension is invented.
    dims = [Dimension("dim_f1" + "0" * 20, "Reading and decoding")]
    suggestion = match_dimensions("He can focus for hours.", dims)
    assert suggestion.dimension_id is None
    # And a name she DID upload matches through the table.
    dims2 = [Dimension("dim_a1" + "0" * 20, "Attention")]
    suggestion2 = match_dimensions("He can focus for hours.", dims2)
    assert suggestion2.dimension_id == dims2[0].id
    assert "focus" in suggestion2.reason


def test_reason_at_most_140_chars_and_hit_verbatim():
    long_name = "Attention and executive function with a very long extension"
    dims = [Dimension("dim_g1" + "0" * 20, long_name)]
    quote = "She is distractible and forgets her books."
    suggestion = match_dimensions(quote, dims)
    assert len(suggestion.reason) <= 140
    quoted = re.findall(r"“([^”]+)”", suggestion.reason)
    hit_fragment = quoted[0]
    assert hit_fragment in quote  # the hit is a verbatim substring


def test_two_hit_reason_at_most_140_chars():
    reason = two_hit_reason(
        "Attention and executive function planning",
        "Reading decoding and word recognition fluency",
    )
    assert len(reason) <= 140
    assert "…" in reason


def test_one_hit_reason_shortens_long_name():
    reason = one_hit_reason("reads", "A" * 200)
    assert len(reason) <= 140


# -- dim_hit verbatim hits ------------------------------------------------------


def test_dim_hit_returns_verbatim_quote_substrings():
    quote = "Mother says he sleeps about 8 hours a night."
    assert dim_hit(quote, "Sleep and routine") == "sleeps"
    assert dim_hit(quote, "sleep") == "sleeps" or dim_hit(quote, "sleep") is None
    hit = dim_hit("He reads very slowly.", "Reading and decoding")
    assert hit is not None and hit in "He reads very slowly."


def test_dim_hit_stop_words_do_not_match():
    # "the" / "daily" etc. must not match even when the quote contains them.
    assert dim_hit("The daily report.", "The daily grind") is None


def test_dim_hit_cjk_skips_connector_bigrams():
    # Bigrams of 与/和/的/情况 are skipped; a name made only of connectors
    # must not hit a quote full of connectors.
    assert dim_hit("孩子的与和的情况", "的情况") is None
    # "孩子" is a real bigram and must hit when the quote contains it.
    assert dim_hit("孩子坐不住", "注意力与孩子") == "孩子"


# -- output filter (rule 4 building blocks) ------------------------------------


def test_blocked_phrases_detected_case_insensitive():
    assert find_blocked_citation("meets criteria") == "meets criteria"
    assert find_blocked_citation("Consistent with a Diagnosis Of X") is not None
    assert find_blocked_citation("suggests a diagnosis") is not None
    assert find_blocked_citation("diagnosed with ADHD") == "diagnosed with"
    assert find_blocked_citation("criteria for ADHD") is not None


def test_criterion_number_citations_detected():
    assert find_blocked_citation("Criterion A1") == "Criterion A1"
    assert find_blocked_citation("see A.1 above") == "A.1"
    assert find_blocked_citation("F90.0") == "F90.0"
    assert find_blocked_citation("314.01") == "314.01"
    assert find_blocked_citation("299.00") == "299.00"


def test_clean_text_passes_the_filter():
    assert find_blocked_citation("Attention during homework") is None
    assert is_safe_dimension_name("Attention")
    assert is_safe_reason("The text mentions “reads”.")


# -- the four hard rules --------------------------------------------------------


class _FakeMatcher:
    """Test double: returns whatever dimensions it was configured to."""

    def __init__(self, result: list[Dimension], hit: str | None = None):
        self._result = result
        self._hit = hit

    def suggest(self, quote: str, dimensions) -> list[Dimension]:
        return list(self._result)

    def hit_for(self, quote: str, dimension) -> str | None:
        return self._hit


def _known(dimensions: list[Dimension]) -> tuple[set[str], dict[str, str]]:
    return {d.id for d in dimensions}, {d.id: d.name for d in dimensions}


QUOTE = "He is distractible and reads slowly."


def test_rule1_unknown_matcher_dimension_is_discarded():
    # A fake matcher naming something outside the table must not survive:
    # the suggestion (as a bad matcher would have written it) carries an
    # id that is not in the uploaded dimensions table.
    real = Dimension("dim_a1" + "0" * 20, "Attention")
    stranger = Dimension("dim_evil" + "0" * 17, "Psychosis")
    suggestion = DimensionSuggestion(
        stranger.id, "needs_review", one_hit_reason("distractible", "Psychosis")
    )
    ids, names = _known([real])
    cleaned = apply_hard_rules(QUOTE, suggestion, ids, names)
    assert cleaned.dimension_id is None
    assert cleaned.state == "needs_review"


def test_rule1_known_matcher_dimension_is_kept():
    real = Dimension("dim_a1" + "0" * 20, "Attention")
    suggestion = match_dimensions(QUOTE, [real], matcher=_FakeMatcher([real], "distractible"))
    ids, names = _known([real])
    cleaned = apply_hard_rules(QUOTE, suggestion, ids, names)
    assert cleaned.dimension_id == real.id


def test_rule2_bad_reason_is_downgraded():
    # A reason that does not quote the evidence -> no dimension, safe reason.
    real = Dimension("dim_a1" + "0" * 20, "Attention")
    suggestion = DimensionSuggestion(
        real.id, "needs_review", "Completely fabricated rationale with no anchor."
    )
    ids, names = _known([real])
    cleaned = apply_hard_rules(QUOTE, suggestion, ids, names)
    assert cleaned.dimension_id is None
    assert cleaned.state == "needs_review"
    assert cleaned.reason == SAFE_REASON


def test_rule2_reason_quoting_the_evidence_is_kept():
    real = Dimension("dim_a1" + "0" * 20, "Attention")
    suggestion = DimensionSuggestion(
        real.id, "needs_review", one_hit_reason("distractible", "Attention")
    )
    ids, names = _known([real])
    cleaned = apply_hard_rules(QUOTE, suggestion, ids, names)
    assert cleaned.dimension_id == real.id
    assert "distractible" in cleaned.reason


def test_rule3_no_list_means_no_mapping():
    suggestion = match_dimensions(QUOTE, None)
    cleaned = apply_hard_rules(QUOTE, suggestion, set(), {})
    assert cleaned.dimension_id is None
    assert cleaned.state == "none"
    assert cleaned.reason == NO_LIST_REASON
    # Even a matcher-provided dimension cannot survive without a list.
    suggestion2 = DimensionSuggestion("dim_a1" + "0" * 20, "needs_review", "distractible")
    cleaned2 = apply_hard_rules(QUOTE, suggestion2, set(), {})
    assert cleaned2.dimension_id is None
    assert cleaned2.reason == NO_LIST_REASON


def test_rule4_blocked_name_is_held_back():
    # Rule 4 for names is enforced at list-build time; the guard here ensures
    # a suggestion carrying a blocked name cannot surface either.
    bad = Dimension("dim_bad" + "0" * 18, "Meets criteria for ADHD")
    suggestion = DimensionSuggestion(
        bad.id, "needs_review", one_hit_reason("attention", "Meets criteria for ADHD")
    )
    ids, names = _known([bad])
    cleaned = apply_hard_rules(QUOTE, suggestion, ids, names)
    assert cleaned.dimension_id is None


def test_rule4_blocked_reason_is_replaced_by_safe_reason():
    real = Dimension("dim_a1" + "0" * 20, "Attention")
    suggestion = DimensionSuggestion(
        real.id,
        "needs_review",
        "The text mentions “attention”, consistent with a diagnosis of X.",
    )
    ids, names = _known([real])
    cleaned = apply_hard_rules(QUOTE, suggestion, ids, names)
    assert cleaned.dimension_id is None
    assert cleaned.state == "needs_review"
    assert cleaned.reason == SAFE_REASON
    assert find_blocked_citation(cleaned.reason) is None


def test_rule4_citation_in_reason_is_replaced():
    real = Dimension("dim_a1" + "0" * 20, "Attention")
    suggestion = DimensionSuggestion(
        real.id, "needs_review", "The text mentions “attention”, like Criterion A1."
    )
    ids, names = _known([real])
    cleaned = apply_hard_rules(QUOTE, suggestion, ids, names)
    assert cleaned.dimension_id is None
    assert cleaned.reason == SAFE_REASON


def test_fixed_reasons_are_exempt_from_rule2():
    # The safe/no-list/stale fixed sentences carry no quote but must survive.
    ids, names = _known([Dimension("dim_a1" + "0" * 20, "Attention")])
    for fixed in (NO_LIST_REASON, SAFE_REASON, STALE_CHOICE_REASON, NO_HIT_REASON):
        cleaned = apply_hard_rules(QUOTE, DimensionSuggestion(None, "none", fixed), ids, names)
        assert cleaned.reason == fixed
        assert len(cleaned.reason) <= 140


def test_dim_rules_version():
    assert DIM_RULES_VERSION == "dim-1"
