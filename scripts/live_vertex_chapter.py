#!/usr/bin/env python3
"""Generate one History chapter from the synthetic fixture with Vertex AI.

Usage (from the repository root, with the live extra):

    PSYCHTOOL_LIVE_VERTEX=1 uv run --extra live python scripts/live_vertex_chapter.py --opt-in

Both the environment flag (``PSYCHTOOL_LIVE_VERTEX=1``) and the command-line
flag (``--opt-in``) are required, and any ``real`` profile or data tier is
refused even then (ADR 0024). Only the synthetic fixture case
``fixtures/case_a001`` may be used; the fixture is copied into a scratch
workspace, so the repository copy is never written.

This script never runs in CI and no test in this repository calls it.
"""

from __future__ import annotations

from psychtool.live.vertex_chapter import main

if __name__ == "__main__":
    raise SystemExit(main())
