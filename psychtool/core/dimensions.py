"""Dimension mapping rules (PT-08 / GROK-38, ADR 0016).

R7: dimensions come ONLY from the list SHE uploaded — there is no built-in
official dimension or criteria list anywhere in the product. Everything in
this module is a verbatim port of the prototype's ``buildCase`` /
``dimHit`` / ``DIM_SYN`` / ``STOP`` logic (cur.html ~878-892), plus the four
hard rules of tech-design §4 which are enforced **in code, not in prompts**.

The four hard rules (each has a dedicated test that fails when the rule is
removed):

1. Only names present in the uploaded ``dimensions`` table may ever be
   referenced; any matcher output naming something outside the table is
   discarded.
2. Every mapping reason must quote visible text of that evidence (a verbatim
   substring of the quote); otherwise the item is downgraded to
   ``needs_review`` with no dimension.
3. No uploaded dimension list -> no mapping at all; the UI shows the
   prototype empty state.
4. The output filter blocks diagnosis-style phrases and criterion-number-
   style citations in dimension names and reasons. A list line containing
   them is held back and counted (never turned into a dimension); a reason
   containing them is replaced by a safe fixed reason and the item becomes
   ``needs_review``. Every dimension view shows the fixed disclaimer.

The matcher itself (``match_dimensions``) only matches HER names against the
evidence quote: a word of >= 4 letters prefix-matching the name, a CJK
bigram of the name, or the synonym table. The synonym table maps name
patterns to quote patterns — it helps match her names, it never creates
names.
"""

from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple, Protocol, Sequence, runtime_checkable

# Bumped whenever the synonym/stop tables change; persisted on mapping rows.
DIM_RULES_VERSION = "dim-1"

# The one fixed disclaimer every dimension view must show (R7-AC6).
NOT_DIAGNOSIS = "This is not a diagnosis. The diagnosis is yours."

# No-list fixed reason (rule 3 / R7-AC2).
NO_LIST_REASON = (
    "No dimension list has been uploaded for this case, so no dimension is assigned."
)

# Fixed reason used when a matcher-produced reason fails the output filter
# (rule 4) or the verbatim-substring check (rule 2).
SAFE_REASON = (
    "The system could not produce a safe reason that quotes the source text, "
    "so no dimension is assigned yet."
)

# Her chosen dimension disappeared from the latest list version.
STALE_CHOICE_REASON = (
    "The dimension you chose is no longer in your list; please check."
)

MAX_REASON_LENGTH = 140
MAX_HIT_LENGTH = 40

DIMENSION_ID_RE = re.compile(r"^dim_[0-9a-f]{24}$")


def is_dimension_id(value: str) -> bool:
    return isinstance(value, str) and DIMENSION_ID_RE.fullmatch(value) is not None


# -- Rule 4: output filter ---------------------------------------------------
#
# Diagnosis-style phrases (R7-AC6) and criterion-number-style citations
# (R7-AC8). These never appear in dimension names or mapping reasons. The
# patterns are deliberately literal: they are fixed strings we refuse to
# carry, not a semantic detector.

DIAGNOSIS_PHRASES: tuple[str, ...] = (
    "meets criteria",
    "consistent with a diagnosis of",
    "diagnosis is",
    "suggests a diagnosis",
    "diagnosed with",
    "criteria for",
    "this is not a diagnosis",
)

_CRITERION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "Criterion A1", "criteria A.1", "criterion 1"
    re.compile(r"\bcriteri(?:a|on)\s+[A-Za-z]{0,2}\.?\s*\d+\b", re.IGNORECASE),
    # DSM/ICD-style numeric codes: F90.0, 314.01, 299.00
    re.compile(r"\b[A-TV-Z]\d{2}\.\d{1,4}\b"),
    re.compile(r"\b\d{3}\.\d{2,4}\b"),
    # "A.1" / "B.2" style criterion numbering
    re.compile(r"\b[A-Z]\.\d{1,2}\b"),
)

_BLOCKED_NAME_TOKENS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdsm\b", re.IGNORECASE),
    re.compile(r"\bicd\b", re.IGNORECASE),
)


def find_blocked_citation(text: str) -> str | None:
    """Return the first blocked fragment of ``text``, or None when clean."""
    lowered = text.casefold()
    for phrase in DIAGNOSIS_PHRASES:
        index = lowered.find(phrase)
        if index >= 0:
            return text[index : index + len(phrase)]
    for pattern in _CRITERION_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return match.group(0)
    return None


def is_safe_dimension_name(name: str) -> bool:
    """Rule 4 (names): no diagnosis phrases, citations or manual tokens."""
    return find_blocked_citation(name) is None and not any(
        pattern.search(name) for pattern in _BLOCKED_NAME_TOKENS
    )


def is_safe_reason(reason: str) -> bool:
    """Rule 4 (reasons): no diagnosis phrases or criterion-number citations."""
    return find_blocked_citation(reason) is None


# -- Dimension list name parsing ----------------------------------------------

# A leading "Dimension N:" / "维度N：" label (digits or Chinese numerals).
_LABEL_RE = re.compile(
    r"^(?:dimension\s*\d+|维度[一二三四五六七八九十\d]+)\s*[：:]\s*", re.IGNORECASE
)
_PAREN_RE = re.compile(r"\s*[（(][^（()）]*[)）]\s*")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")

MIN_NAME_CHARS = 2
MAX_NAME_CHARS = 80


def _display_width(text: str) -> int:
    """Approximate terminal/display width: CJK wide, others narrow."""
    return sum(
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in text
    )


def parse_dimension_line(line: str) -> str | None:
    """Turn one list line into a dimension name (prototype ``buildCase`` port).

    Strip a leading ``Dimension N:`` / ``维度N：`` label, strip one
    parenthetical, strip one trailing ``.``/``。``, trim. The result is a
    dimension only when it is 2-80 display characters wide; a full sentence
    (>= 12 words) is never a dimension (the prototype's intro line "This is a
    clinician-made working list…" must not become one).
    """
    name = _LABEL_RE.sub("", line.strip())
    name = _PAREN_RE.sub(" ", name).strip()
    if name.endswith((".", "。")):
        name = name[:-1].strip()
    if not name:
        return None
    if len(_WORD_RE.findall(name)) >= 12:
        return None
    width = _display_width(name)
    if width < MIN_NAME_CHARS or width > MAX_NAME_CHARS:
        return None
    return name


# -- Matcher -------------------------------------------------------------------

# Prototype DIM_SYN port: each entry maps a dimension-NAME pattern to a
# QUOTE-text pattern. It only helps match her names; it never creates names.
DIM_SYN: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (
        re.compile(r"attention|focus|engag", re.IGNORECASE),
        re.compile(r"\b(distract\w*|focus\w*|sit still|on task|attention)\b", re.IGNORECASE),
    ),
    (
        re.compile(r"read|decod|word", re.IGNORECASE),
        re.compile(r"\b(read\w*|misread\w*|words?)\b", re.IGNORECASE),
    ),
    (
        re.compile(r"sleep|routine", re.IGNORECASE),
        re.compile(r"\b(sleep\w*|asleep|bedtime)\b", re.IGNORECASE),
    ),
    (
        re.compile(r"social|interaction|peer", re.IGNORECASE),
        re.compile(r"\b(classmates|friends?|peers?)\b", re.IGNORECASE),
    ),
    (
        re.compile(r"mood|emotion", re.IGNORECASE),
        re.compile(r"\b(mood|irritable|upset|sad|worried|anxious)\b", re.IGNORECASE),
    ),
    (
        re.compile(r"memory|speed", re.IGNORECASE),
        re.compile(r"\b(forget\w*|remember\w*|memory|slow)\b", re.IGNORECASE),
    ),
)

# Prototype STOP port: name words (and CJK bigrams) that never count as a hit.
STOP: re.Pattern[str] = re.compile(
    r"^(and|the|with|for|daily|dimension|during|of|to|in)$", re.IGNORECASE
)

# CJK bigrams made only of these connector characters are skipped (prototype
# port: bigrams that are only 与/和/的/情况/维度, simplified and traditional).
_CJK_BIGRAM_SKIP_CHARS: frozenset[str] = frozenset("与和的情况维度況與")

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _is_cjk(char: str) -> bool:
    return _CJK_RE.fullmatch(char) is not None


class Dimension(NamedTuple):
    """One row of HER uploaded dimension list."""

    id: str
    name: str


@runtime_checkable
class DimensionMatcher(Protocol):
    """Pluggable matcher; ``_DefaultMatcher`` below is the built-in one.

    Tests substitute fakes that return unknown ids or bad reasons to prove
    the four hard rules hold in the store, not in the matcher. The default
    protocol method returns the matched dimensions for one quote (hits
    only); :func:`match_dimensions` extracts each hit's verbatim substring
    via :func:`dim_hit` unless the matcher provides it.
    """

    def suggest(self, quote: str, dimensions: Sequence[Dimension]) -> list[Dimension]: ...


def _bigrams(name: str) -> list[str]:
    chars = [char for char in name if not char.isspace()]
    return [a + b for a, b in zip(chars, chars[1:])]


_NAME_SPLIT_RE = re.compile(r"[^A-Za-z]+")


def dim_hit(quote: str, name: str) -> str | None:
    """The prototype ``dimHit``: a verbatim quote substring close to ``name``.

    Returns the hit substring (always a verbatim slice of the quote), or
    None. Prototype order:

    1. CJK name: try each bigram (skipping connector bigrams), return the
       first one contained in the quote; if none matches, return None —
       do NOT fall through to the other checks.
    2. Latin name: for each name word (split on non-letters) of length
       >= 4 that is not a STOP word, if the quote matches
       ``\\b`` + first 4 letters + ``\\w*`` case-insensitively, return the
       matched quote substring.
    3. Synonym table: a name-pattern matching the name plus a quote-pattern
       matching the quote -> that quote match.
    4. Otherwise None.
    """
    if any(_is_cjk(char) for char in name):
        for bigram in _bigrams(name):
            if any(_is_cjk(char) for char in bigram) and not all(
                char in _CJK_BIGRAM_SKIP_CHARS for char in bigram
            ):
                index = quote.find(bigram)
                if index >= 0:
                    return quote[index : index + 2]
        return None
    for word in _NAME_SPLIT_RE.split(name):
        if len(word) < 4 or STOP.fullmatch(word):
            continue
        match = re.search(r"\b" + re.escape(word[:4]) + r"\w*", quote, re.IGNORECASE)
        if match is not None:
            return match.group(0)
    for name_pattern, quote_pattern in DIM_SYN:
        if name_pattern.search(name):
            match = quote_pattern.search(quote)
            if match is not None:
                return match.group(0)
    return None


def _cap_hit(hit: str) -> str:
    return hit[:MAX_HIT_LENGTH]


def _shorten(name: str, budget: int) -> str:
    """Trim a name to ``budget`` display characters, adding "…" when cut."""
    if _display_width(name) <= budget:
        return name
    out: list[str] = []
    width = 0
    for char in name:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if width + char_width > budget - 1:
            break
        out.append(char)
        width += char_width
    return "".join(out) + "…"


ONE_HIT_TEMPLATE = (
    "“{hit}” in the text is close to the dimension “{name}”. "
    "The system only matched words, so please check."
)


def one_hit_reason(hit: str, name: str) -> str:
    """Rule: <= 140 chars; the hit is a verbatim substring of the quote."""
    hit = _cap_hit(hit)
    reason = ONE_HIT_TEMPLATE.format(hit=hit, name=name)
    if len(reason) <= MAX_REASON_LENGTH:
        return reason
    budget = MAX_REASON_LENGTH - len(ONE_HIT_TEMPLATE.format(hit=hit, name=""))
    return ONE_HIT_TEMPLATE.format(hit=hit, name=_shorten(name, budget))


TWO_HIT_TEMPLATE = (
    "Could relate to “{a}” or to “{b}”. "
    "The system cannot tell, so no dimension is assigned yet."
)


def two_hit_reason(first: str, second: str) -> str:
    reason = TWO_HIT_TEMPLATE.format(a=first, b=second)
    if len(reason) <= MAX_REASON_LENGTH:
        return reason
    budget = (
        MAX_REASON_LENGTH
        - len(TWO_HIT_TEMPLATE.format(a="", b=""))
    ) // 2
    return TWO_HIT_TEMPLATE.format(a=_shorten(first, budget), b=_shorten(second, budget))


NO_HIT_REASON = (
    "Nothing in this text matches a dimension name in your list, "
    "so no dimension is assigned."
)


class DimensionSuggestion(NamedTuple):
    """One evidence item's dimension suggestion (before her choice)."""

    dimension_id: str | None  # None -> no dimension (none / ambiguous)
    state: str  # 'needs_review' | 'none'
    reason: str


def match_dimensions(
    quote: str,
    dimensions: Sequence[Dimension] | None,
    matcher: DimensionMatcher | None = None,
) -> DimensionSuggestion:
    """Suggest a dimension for one evidence quote (the dim-1 rules).

    Exactly one hit -> ``needs_review`` with that dimension; two or more ->
    ``needs_review`` with NO dimension; none -> ``none``; no list at all ->
    ``none`` with the no-list fixed reason. The caller (the store) applies
    the four hard rules afterwards — this function is trusted for nothing.
    """
    matcher = matcher or _DefaultMatcher()
    if not dimensions:
        return DimensionSuggestion(None, "none", NO_LIST_REASON)
    matched = matcher.suggest(quote, dimensions)
    matched_ids = {item.id for item in matched}
    hits: list[tuple[Dimension, str]] = []
    for dimension in dimensions:
        if dimension.id not in matched_ids:
            continue
        hit = getattr(matcher, "hit_for", None)
        hit_text = hit(quote, dimension) if callable(hit) else dim_hit(quote, dimension.name)
        if hit_text is not None:
            hits.append((dimension, hit_text))
    if len(hits) == 1:
        dimension, hit = hits[0]
        return DimensionSuggestion(
            dimension.id, "needs_review", one_hit_reason(hit, dimension.name)
        )
    if len(hits) >= 2:
        return DimensionSuggestion(
            None,
            "needs_review",
            two_hit_reason(hits[0][0].name, hits[1][0].name),
        )
    return DimensionSuggestion(None, "none", NO_HIT_REASON)


class _DefaultMatcher:
    """The built-in matcher: prototype ``dimHit`` per dimension."""

    def suggest(self, quote: str, dimensions: Sequence[Dimension]) -> list[Dimension]:
        return [d for d in dimensions if dim_hit(quote, d.name) is not None]

    def hit_for(self, quote: str, dimension: Dimension) -> str | None:
        return dim_hit(quote, dimension.name)


# -- The four hard rules -------------------------------------------------------


def apply_hard_rules(
    quote: str,
    suggestion: DimensionSuggestion,
    known_ids: set[str],
    known_names: dict[str, str],
    matcher: DimensionMatcher | None = None,
) -> DimensionSuggestion:
    """Enforce hard rules 1, 2 and 4 on one matcher suggestion.

    Rule 1: a suggested dimension id must be in the uploaded table.
    Rule 2: the reason must quote a verbatim substring of the quote.
    Rule 4: names and reasons must pass the output filter; a failed reason
    is replaced by the safe fixed reason and the dimension is dropped.

    Her choices are applied afterwards by the store (they always win).
    """
    _ = matcher  # the rules never trust the matcher's internals
    dimension_id, state, reason = suggestion
    if not known_names:
        # Rule 3: no dimension list -> no mapping at all.
        return DimensionSuggestion(None, "none", NO_LIST_REASON)
    if dimension_id is not None and dimension_id not in known_ids:
        dimension_id, state = None, "needs_review"  # rule 1
    if dimension_id is not None:
        name = known_names.get(dimension_id)
        if name is None or not is_safe_dimension_name(name):
            dimension_id, state = None, "needs_review"  # rule 4 (name)
    if not is_safe_reason(reason):
        dimension_id, state = None, "needs_review"  # rule 4 (reason)
        reason = SAFE_REASON
    elif reason and reason not in (
        NO_LIST_REASON,
        NO_HIT_REASON,
        SAFE_REASON,
        STALE_CHOICE_REASON,
    ):
        # Rule 2: the reason must point at visible text. Fixed system
        # sentences need no quote; any other reason must contain a substring
        # of the quote (or, for the ambiguous branch, of the dimension names).
        lowered_quote = quote.casefold()
        names_folded = [name.casefold() for name in known_names.values()]
        quoted = re.findall(r"“([^”]+)”", reason)
        if quoted:
            ok = any(
                fragment.casefold() in lowered_quote
                or any(fragment.casefold() in name for name in names_folded)
                for fragment in quoted
            )
        else:
            ok = any(
                len(fragment) >= 4
                and (
                    fragment.casefold() in lowered_quote
                    or any(fragment.casefold() in name for name in names_folded)
                )
                for fragment in re.split(r"\W+", reason)
                if fragment
            )
        if not ok:
            dimension_id, state = None, "needs_review"
            reason = SAFE_REASON
    if len(reason) > MAX_REASON_LENGTH:
        reason = reason[: MAX_REASON_LENGTH - 1] + "…"
    return DimensionSuggestion(dimension_id, state, reason)
