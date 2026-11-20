"""Seed a demo workspace for the Web UI from the synthetic fixture.

Creates ``local-data/workspaces/<case_id>`` for every case in
``fixtures/adolescent-background.json`` so the server can load it right away.
Only synthetic material is used; re-running is a no-op for existing cases.

Usage:
    python scripts/seed_demo.py
"""

from __future__ import annotations

import json
from pathlib import Path

from psychtool.core.eval import build_workspace
from psychtool.core.workspace import set_known_names

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "adolescent-background.json"
WORKSPACES = ROOT / "local-data" / "workspaces"

# A clearly synthetic name so the redaction panel is not empty in the demo.
DEMO_NAMES = ["虚构青少年 A"]


def main() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    WORKSPACES.mkdir(parents=True, exist_ok=True)
    for case in fixture["cases"]:
        target = WORKSPACES / case["case_id"]
        if target.exists():
            print(f"skip {case['case_id']}: already at {target}")
            continue
        ws = build_workspace(case, WORKSPACES)
        set_known_names(ws, DEMO_NAMES)
        print(f"seeded {ws}")
    print(f"\nworkspaces root: {WORKSPACES}")


if __name__ == "__main__":
    main()
