"""Manual, opt-in live paths (ADR 0024).

Nothing in this package runs automatically: every entry point needs an
explicit environment flag *and* an explicit command-line flag, and the
``real`` profile / data tier is refused even then.
"""

from __future__ import annotations

__all__ = ["vertex_chapter"]
