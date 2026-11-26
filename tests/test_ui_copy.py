"""Byte-exact PT-14 clinician copy (tech-design.md §7 / Q5 and ADR 0023)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPY_TS = (ROOT / "web" / "src" / "copy.ts").read_text(encoding="utf-8")
ADR = (ROOT / "docs" / "adr" / "0023-desktop-launcher-and-error-copy.md").read_text(
    encoding="utf-8"
)

OFFLINE_MESSAGE = (
    "You're offline. Your saved work is safe on this computer. "
    "Sending to the AI assistant will work again when you're back online."
)
SAVE_FAILURE_MESSAGE = (
    "We couldn't save this section. Your text is still here. "
    "Copy it somewhere safe, then try Save again."
)
SERVICE_NOT_RUNNING_MESSAGE = (
    "The writing workspace isn't running on this computer. "
    "Double-click Start Psychtool, then reload this page. "
    "If that doesn't help, ask the person who installed it."
)


def _exported_string(name: str) -> str:
    match = re.search(rf'export const {name} =\s*"((?:\\.|[^"\\])*)"', COPY_TS)
    assert match is not None, f"{name} not found in copy.ts"
    return match.group(1)


def test_offline_copy_is_byte_exact_with_tech_design_q5():
    assert _exported_string("OFFLINE_MESSAGE") == OFFLINE_MESSAGE
    assert OFFLINE_MESSAGE in ADR


def test_save_failure_copy_is_byte_exact_with_tech_design_q5():
    assert _exported_string("SAVE_FAILURE_MESSAGE") == SAVE_FAILURE_MESSAGE
    assert SAVE_FAILURE_MESSAGE in ADR


def test_service_not_running_copy_is_byte_exact_with_adr_0023():
    assert _exported_string("SERVICE_NOT_RUNNING_MESSAGE") == SERVICE_NOT_RUNNING_MESSAGE
    assert SERVICE_NOT_RUNNING_MESSAGE in ADR
