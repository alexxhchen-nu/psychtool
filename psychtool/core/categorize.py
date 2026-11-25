"""Evidence categorization rules (PT-07 / GROK-37, ADR 0015).

R5: every evidence item gets one suggested category and a short reason, for
her judgement — never a conclusion. The keyword tables below are a verbatim
port of the prototype ``CAT_KW`` / ``ROLE_KW`` (cur.html ~870-880): plain
alternation, first match wins, case-insensitive, matched directly against the
stored quote so every keyword is a verbatim substring of the source text.

Two invariants carry the requirement:

- the reason always quotes the exact matched keyword (capped at 40 chars) and
  the whole reason stays <= 140 characters (~two lines), so it always points
  at visible source text (R5-AC1);
- when no keyword matches, the suggestion is ``uncategorized`` — never a
  plausible-looking guess and never ``other``: ``other`` is only for her to
  choose (R5-AC2).

Provider role is recorded separately from category, with the same
matched-keyword reason shape; when nothing says who provided the text the
role is ``to_confirm`` for her to confirm.

``CategorizeRules`` carries both tables plus a version string so tests (and
later rule updates) can swap the tables and prove that persisted evidence ids
and her corrections survive a rules change (ADR 0015).
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Bumped whenever the keyword tables change; persisted on every evidence row.
RULES_VERSION = "rule-1"

CATEGORY_KEYS: frozenset[str] = frozenset(
    {
        "family_history",
        "medical_history",
        "test_results",
        "behavioral_observations",
        "development_school",
        "daily_living",
        "other",
        "uncategorized",
    }
)
ROLE_KEYS: frozenset[str] = frozenset(
    {"school", "caregiver", "medical_record", "clinician", "client", "to_confirm"}
)

# Longest keyword the reason may quote; keeps the reason within two lines.
MAX_KEYWORD_LENGTH = 40
MAX_REASON_LENGTH = 140

UNCATEGORIZED_REASON = (
    "No words in the text indicate a category, so the system does not choose for you."
)
ROLE_CONFIRM_REASON = "Nothing in the text says who provided it; please confirm."


class CategoryRule(NamedTuple):
    key: str
    label: str
    pattern: re.Pattern[str]


class RoleRule(NamedTuple):
    key: str
    label: str
    pattern: re.Pattern[str]


class CategorizeRules(NamedTuple):
    """One versioned rule set (swap in tests / future rule updates)."""

    version: str
    categories: tuple[CategoryRule, ...]
    roles: tuple[RoleRule, ...]


def _kw(alternation: str) -> re.Pattern[str]:
    """One prototype keyword alternation, case-insensitive like CAT_KW."""
    return re.compile(f"(?:{alternation})", re.IGNORECASE)


_CATEGORY_TABLE: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "family_history",
        "Family history",
        _kw(
            r"\b(father|uncle|aunt|grand(mother|father|parents?)|siblings?|brother"
            r"|sister|cousin|family history)\b"
            r"|舅舅|姑姑|叔叔|外公|外婆|爷爷|奶奶|家族|亲属"
        ),
    ),
    (
        "medical_history",
        "Medical history",
        _kw(
            r"\b(hospital\w*|medication|medicine|allerg\w*|surgery|premature"
            r"|clinic|head injury|seizures?)\b"
            r"|医院|住院|早产|服药|过敏|手术|病史"
        ),
    ),
    (
        "test_results",
        "Test results",
        _kw(r"\b(index|scores?|percentile|standard score|scaled score)\b|指数|分数|百分位|得分"),
    ),
    (
        "behavioral_observations",
        "Behavioral observations",
        _kw(r"\b(during testing|observed|testing session|in the session)\b|测评中|施测|观察到"),
    ),
    (
        "development_school",
        "Development & school",
        _kw(
            r"\b(school|teacher\w*|class(room)?|grades?|homework|read\w*|spell\w*"
            r"|writ\w*|math|walk\w*|talk\w*|speech)\b"
            r"|学校|老师|成绩|作业|阅读|朗读|年级|上课|课堂"
        ),
    ),
    (
        "daily_living",
        "Daily living & function",
        _kw(
            r"\b(sleep\w*|asleep|bed(time)?|friends?|classmates|peers|chores"
            r"|meals?|phone|routine|mood|irritable|dress\w*)\b"
            r"|睡|吃饭|朋友|同学|家务|自理|作息|手机|心情"
        ),
    ),
)

_ROLE_TABLE: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("school", "School", _kw(r"\bteacher|\bschool\b|老师|学校|班主任")),
    (
        "caregiver",
        "Caregiver",
        _kw(r"\b(mother|father|parent|caregiver|grandparent)s? (reports?|says|said|notes?)\b|母亲称|父亲称|家长"),
    ),
    (
        "medical_record",
        "Medical record",
        _kw(r"\bmedical record|\bhospital record|病历"),
    ),
    ("clinician", "Clinician", _kw(r"\bduring testing\b|\bobserved\b|测评中|施测|观察到")),
    # Only the bare "I" is case-sensitive in the prototype (lowercase "i" is
    # not a source); the other client keywords stay case-insensitive.
    (
        "client",
        "Client",
        re.compile(
            r"\bthe client says\b|\bclient reports\b|(?-i:\bI\b)|来访者说",
            re.IGNORECASE,
        ),
    ),
)


def default_rules() -> CategorizeRules:
    """The built-in ``rule-1`` tables (prototype port)."""
    return CategorizeRules(
        version=RULES_VERSION,
        categories=tuple(CategoryRule(*row) for row in _CATEGORY_TABLE),
        roles=tuple(RoleRule(*row) for row in _ROLE_TABLE),
    )


def _keyword_in(pattern: re.Pattern[str], quote: str) -> str | None:
    """The exact matched substring (verbatim quote slice), or None."""
    match = pattern.search(quote)
    if match is None:
        return None
    return match.group(0)


def _cap_keyword(keyword: str) -> str:
    """Cap a matched keyword at 40 chars, code-point safe."""
    return keyword[:MAX_KEYWORD_LENGTH]


def suggest_category(quote: str, rules: CategorizeRules | None = None) -> tuple[str, str, str]:
    """Suggest ``(key, label, reason)`` for one verbatim quote.

    First matching table row wins. No match -> ``uncategorized`` with the
    fixed R5-AC2 reason; the rules never emit ``other``.
    """
    rules = rules or default_rules()
    for rule in rules.categories:
        keyword = _keyword_in(rule.pattern, quote)
        if keyword is None:
            continue
        shown = _cap_keyword(keyword)
        reason = f"The text mentions “{shown}”, which relates to “{rule.label}”."
        return rule.key, rule.label, reason[:MAX_REASON_LENGTH]
    return "uncategorized", "Uncategorized", UNCATEGORIZED_REASON


def suggest_role(quote: str, rules: CategorizeRules | None = None) -> tuple[str, str, str]:
    """Suggest ``(key, label, reason)`` for who provided the text."""
    rules = rules or default_rules()
    for rule in rules.roles:
        keyword = _keyword_in(rule.pattern, quote)
        if keyword is None:
            continue
        shown = _cap_keyword(keyword)
        reason = f"The text says “{shown}”."
        return rule.key, rule.label, reason[:MAX_REASON_LENGTH]
    return "to_confirm", "To confirm", ROLE_CONFIRM_REASON
