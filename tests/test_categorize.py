"""PT-07 (R5 / GROK-37): categorize rule unit tests.

Covers every category and role keyword family (including Chinese), the
first-match order, the case-sensitive bare "I", the reason shape and its
140-character cap, and the two R5 invariants: the matched keyword is a
verbatim substring of the quote, and the rules never emit ``other``.
"""

from __future__ import annotations

import re

import pytest

from psychtool.core.categorize import (
    CATEGORY_KEYS,
    MAX_REASON_LENGTH,
    ROLE_CONFIRM_REASON,
    ROLE_KEYS,
    RULES_VERSION,
    UNCATEGORIZED_REASON,
    default_rules,
    suggest_category,
    suggest_role,
)

# (quote, expected key) — one representative per category keyword family.
CATEGORY_CASES = [
    ("His father has a similar reading profile.", "family_history"),
    ("The uncle on his mother's side had seizures.", "family_history"),
    ("舅舅也有类似的学习困难。", "family_history"),
    ("家族里有阅读困难的亲属。", "family_history"),
    ("He was hospitalized twice for asthma.", "medical_history"),
    ("She takes medication every morning.", "medical_history"),
    ("过敏史：青霉素过敏。", "medical_history"),
    ("早产，住过保温箱。", "medical_history"),
    ("The index scores are in the average range.", "test_results"),
    ("百分位在第 25 位。", "test_results"),
    ("During testing he asked for extra time.", "behavioral_observations"),
    ("施测中观察到他很紧张。", "behavioral_observations"),
    ("Teacher says he reads slowly in class.", "development_school"),
    ("His homework takes two hours every night.", "development_school"),
    ("老师反映上课容易走神。", "development_school"),
    ("He walks to school with a neighbour.", "development_school"),
    ("He sleeps about 8 hours a night.", "daily_living"),
    ("周末会和同学一起打球。", "daily_living"),
    ("He often stays on his phone until late.", "daily_living"),
]

ROLE_CASES = [
    ("Teacher says he reads slowly in class.", "school"),
    ("班主任提到他最近成绩下滑。", "school"),
    ("Mother says he sleeps about 8 hours a night.", "caregiver"),
    ("父亲称他最近睡眠不好。", "caregiver"),
    ("The medical record lists a head injury in 2024.", "medical_record"),
    ("病历显示曾住院治疗。", "medical_record"),
    ("During testing he worked slowly but carefully.", "clinician"),
    ("测评中他比较安静。", "clinician"),
    ("I often stay up late on my phone.", "client"),
    ("The client says reading is tiring.", "client"),
    ("来访者说最近压力大。", "client"),
]


@pytest.mark.parametrize("quote,key", CATEGORY_CASES)
def test_category_keywords(quote, key):
    got, label, reason = suggest_category(quote)
    assert got == key
    assert got in CATEGORY_KEYS
    assert label
    assert reason


@pytest.mark.parametrize("quote,key", ROLE_CASES)
def test_role_keywords(quote, key):
    got, label, reason = suggest_role(quote)
    assert got == key
    assert got in ROLE_KEYS
    assert label
    assert reason


def test_first_match_wins_for_categories():
    # "father" (family) appears before "school" (development): family wins.
    key, _, _ = suggest_category("His father picks him up from school.")
    assert key == "family_history"
    # "medication" (medical) appears before "scores" (test results).
    key, _, _ = suggest_category("The medication did not change his scores.")
    assert key == "medical_history"


def test_first_match_wins_for_roles():
    # school is checked before caregiver.
    key, _, _ = suggest_role("Mother says the teacher is supportive.")
    assert key == "school"


def test_matching_is_case_insensitive():
    key, _, _ = suggest_category("HOSPITALIZED after a HEAD INJURY.")
    assert key == "medical_history"
    key, _, _ = suggest_role("TEACHER REPORTS progress.")
    assert key == "school"


def test_bare_i_is_case_sensitive():
    # Lowercase "i" alone must not make the item a client statement.
    key, _, reason = suggest_role("i think the schedule is fine.")
    assert key == "to_confirm"
    assert reason == ROLE_CONFIRM_REASON
    # But the sentence-initial capital "I" is a client source.
    key, _, _ = suggest_role("I keep a paper planner.")
    assert key == "client"


def test_uncategorized_when_nothing_matches():
    key, label, reason = suggest_category("The weather was cloudy that week.")
    assert key == "uncategorized"
    assert label == "Uncategorized"
    assert reason == UNCATEGORIZED_REASON


def test_rules_never_emit_other():
    # "Other" is only for her to choose; no keyword maps to it.
    for quote, _ in CATEGORY_CASES:
        assert suggest_category(quote)[0] != "other"
    assert suggest_category("The weather was cloudy that week.")[0] != "other"


def test_uncategorized_role_when_nothing_matches():
    key, label, reason = suggest_role("The weather was cloudy that week.")
    assert key == "to_confirm"
    assert label == "To confirm"
    assert reason == ROLE_CONFIRM_REASON


def test_reason_quotes_verbatim_keyword_substring():
    quote = "Teacher says he reads slowly in class."
    key, _, reason = suggest_category(quote)
    assert key == "development_school"
    keyword = reason.split("“")[1].split("”")[0]
    assert keyword in quote
    _, _, role_reason = suggest_role(quote)
    role_keyword = role_reason.split("“")[1].split("”")[0]
    assert role_keyword in quote


def test_reason_fits_two_lines():
    for quote, _ in CATEGORY_CASES:
        assert len(suggest_category(quote)[2]) <= MAX_REASON_LENGTH
        assert len(suggest_role(quote)[2]) <= MAX_REASON_LENGTH
    # A pathological quote cannot push the reason past the cap either.
    long_quote = "school " * 40
    assert len(suggest_category(long_quote)[2]) <= MAX_REASON_LENGTH


def test_keyword_is_capped_at_40_chars():
    quote = "x" * 60 + " school " + "y" * 60
    _, _, reason = suggest_category(quote)
    keyword = reason.split("“")[1].split("”")[0]
    assert len(keyword) <= 40
    assert keyword in quote


def test_rules_version_is_stable():
    assert RULES_VERSION == "rule-1"
    assert default_rules().version == "rule-1"


def test_rule_tables_are_allowlisted():
    rules = default_rules()
    assert {rule.key for rule in rules.categories} <= CATEGORY_KEYS - {"other", "uncategorized"}
    assert {rule.key for rule in rules.roles} <= ROLE_KEYS - {"to_confirm"}
    for rule in rules.categories + rules.roles:
        assert isinstance(rule.pattern, re.Pattern)
