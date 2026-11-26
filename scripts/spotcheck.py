#!/usr/bin/env python3
"""Run the M1 developer spot-check checklist on synthetic data.

Usage (from the repository root, with the dev extra):

    uv run --extra dev python scripts/spotcheck.py

This is a developer aid, not the PRD §5 product-success gate (that
proposal is still Open and needs the psychologist's agreement). It
never writes a report export.
"""

from __future__ import annotations

from psychtool.acceptance.spotcheck import main

if __name__ == "__main__":
    raise SystemExit(main())
