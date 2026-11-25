"""Protected test-content screen (R13 / PT-05 / ADR 0013).

Keyword list ported verbatim from the prototype. English terms use word
boundaries (so "normal", "normally", "abnormal" and "enormous" never match);
Chinese terms match as plain substrings because Chinese has no word
boundaries. Matching is case-insensitive. Before matching, one NFKC-normalized
copy of the text is used (compatibility full-width letters/digits and
ideographic spaces match their ASCII forms); stored text stays untouched.

Fail-closed contract (R13-AC2): callers must treat *any* exception from this
module as "the whole upload is suspect" and reject it — never fall back to
storing unchecked text. There is no release/override path in M1.

Also hosts the shared rejection vocabulary and :func:`filter_protected_passages`,
the single choke-point used by every ingest path (server upload, CLI import,
JSON workspace store) so blocked passages are never written anywhere.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.core.workspace import Passage

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

# Fixed R13 rejection vocabulary (ADR 0013). The message never quotes the
# filename, the title, or any blocked text; the count is filled in by the
# client from ``blocked_paragraphs``.
PROTECTED_CONTENT_REASON = "protected_content"
PROTECTED_CHECK_FAILED_REASON = "protected_check_failed"
PROTECTED_CONTENT_MESSAGE = (
    "Paragraphs were held back: they appear to contain test items, norms or "
    "scoring rules. They were not added to this case and will never be sent "
    "to the AI assistant. A way to request release will come in a later version."
)
PROTECTED_CHECK_FAILED_MESSAGE = (
    "The upload could not be checked for protected test content, so it was "
    "rejected. Nothing was stored. Try again; if it keeps failing, contact support."
)


class ProtectedContentError(ValueError):
    """An R13 upload rejection: an allowlisted ``reason`` plus fixed text."""

    def __init__(self, reason: str) -> None:
        if reason not in (PROTECTED_CONTENT_REASON, PROTECTED_CHECK_FAILED_REASON):
            raise ValueError(f"unknown protected-content reason: {reason!r}")
        self.reason = reason
        message = (
            PROTECTED_CONTENT_MESSAGE
            if reason == PROTECTED_CONTENT_REASON
            else PROTECTED_CHECK_FAILED_MESSAGE
        )
        super().__init__(message)


def _normalize_for_matching(text: str) -> str:
    """NFKC-normalize a copy of the text for matching only (PT-06).

    Full-width letters/digits and compatibility ideographic spaces become
    their ASCII counterparts so a pasted full-width "Ｎｏｒｍ ｔａｂｌｅ"
    still trips the screen. The stored text is never touched.
    """
    return unicodedata.normalize("NFKC", text)


def is_protected(text: str) -> bool:
    """True when one passage's text matches the protected-content screen."""
    return _PROTECTED_RE.search(_normalize_for_matching(text)) is not None


def find_protected(passages: list[str]) -> list[int]:
    """Indexes of passages that match the protected-content screen.

    The caller drops these passages *before* any store write; the indexes are
    into the caller's list, so the caller decides how stored numbering stays
    consistent with what it keeps.
    """
    return [index for index, text in enumerate(passages) if is_protected(text)]


def filter_protected_passages(
    passages: list[Passage],
) -> tuple[list[Passage], int, str | None]:
    """Drop passages matching the R13 screen; fail closed on any checker error.

    Kept passages are renumbered contiguously from ``p001`` so stored passage
    ids and positions always line up with the text actually stored (quotes and
    char ranges are computed against the stored text). Returns
    ``(kept, blocked_count, blocked_hash)`` where the hash is sha256 of the
    blocked passages' text joined with ``"\\n\\n"`` (None when nothing blocked).

    Raises :class:`ProtectedContentError` with reason ``protected_check_failed``
    when the screen itself errors; nothing may be written by the caller in
    that case.
    """
    from psychtool.core.workspace import Passage  # local import: avoid cycle

    try:
        blocked_indexes = find_protected([passage.text for passage in passages])
    except Exception:
        # Fail closed (R13-AC2): a checker that errors rejects the whole
        # upload; nothing is written, not even an audit row.
        raise ProtectedContentError(PROTECTED_CHECK_FAILED_REASON) from None
    if not blocked_indexes:
        return passages, 0, None
    blocked = set(blocked_indexes)
    kept = [
        Passage(id=f"p{position:03d}", text=passage.text)
        for position, passage in enumerate(
            (p for i, p in enumerate(passages) if i not in blocked), start=1
        )
    ]
    blocked_hash = hashlib.sha256(
        "\n\n".join(passages[i].text for i in blocked_indexes).encode("utf-8")
    ).hexdigest()
    return kept, len(blocked_indexes), blocked_hash
