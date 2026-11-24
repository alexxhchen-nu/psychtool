"""Protected test-content screen (R13 / PT-05 / ADR 0013).

Keyword list ported verbatim from the prototype. English terms use word
boundaries (so "normal", "normally", "abnormal" and "enormous" never match);
Chinese terms match as plain substrings because Chinese has no word
boundaries. Matching is case-insensitive.

Fail-closed contract (R13-AC2): callers must treat *any* exception from this
module as "the whole upload is suspect" and reject it — never fall back to
storing unchecked text. There is no release/override path in M1.
"""

from __future__ import annotations

import re

# One pattern per term, joined with alternation. Kept as separate raw strings
# so the word-boundary structure of the prototype list stays readable.
_PATTERNS = (
    r"\btest (?:item|question)s?\b",
    r"\bnorms?\b",
    r"\bnorm(?:ative)? tables?\b",
    r"\bscoring (?:rules?|keys?|criteria)\b",
    r"\bconversion tables?\b",
    r"\braw[- ]score tables?\b",
    # Chinese terms: substring matching (no \b in Chinese text).
    "原题",
    "常模",
    "计分规则",
    "评分标准",
    "换算表",
)

_PROTECTED_RE = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def is_protected(text: str) -> bool:
    """True when one passage's text matches the protected-content screen."""
    return _PROTECTED_RE.search(text) is not None


def find_protected(passages: list[str]) -> list[int]:
    """Indexes of passages that match the protected-content screen.

    The caller drops these passages *before* any store write; the indexes are
    into the caller's list, so the caller decides how stored numbering stays
    consistent with what it keeps.
    """
    return [index for index, text in enumerate(passages) if is_protected(text)]
