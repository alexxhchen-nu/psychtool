"""Core must not pull in presentation (rich/textual) or network libs."""

import sys

_BANNED_PREFIXES = (
    "rich",
    "textual",
    "socket",
    "requests",
    "httpx",
    "urllib3",
    "aiohttp",
)


def _snapshot() -> set:
    return set(sys.modules)


def test_core_does_not_import_presentation_or_network():
    before = _snapshot()
    import psychtool.core  # noqa: F401
    after = _snapshot()
    newly_loaded = after - before
    offenders = {
        name
        for name in newly_loaded
        if name.split(".")[0] in _BANNED_PREFIXES or name in _BANNED_PREFIXES
    }
    assert not offenders, f"core pulled in banned modules: {sorted(offenders)}"
