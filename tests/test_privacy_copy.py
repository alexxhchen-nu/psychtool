"""R15: the shipped UI keeps the privacy banner and does not claim HIPAA compliance."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "web" / "src"
BANNER = (
    "Please note: This prototype is not HIPAA compliant yet. "
    "Do not enter real patient information. "
    "Use only synthetic or separately approved practice materials."
)
FORBIDDEN_CLAIMS = (
    "符合 HIPAA",
    "已保护全部患者隐私",
    "已保護全部患者隱私",
    "is HIPAA compliant",
    "meets HIPAA",
)


def _source_files():
    for pattern in ("*.ts", "*.tsx", "*.css", "*.html"):
        yield from SRC.rglob(pattern)
    index = REPO / "web" / "index.html"
    if index.exists():
        yield index


def test_r15_ac1_privacy_banner_constant_is_the_approved_text():
    app = (SRC / "App.tsx").read_text(encoding="utf-8")
    assert f"PRIVACY_BANNER = '{BANNER}'" in app or f'PRIVACY_BANNER = "{BANNER}"' in app


def test_r15_ac2_shipped_ui_does_not_claim_hipaa_compliance():
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8-sig")
        relative = path.relative_to(REPO)
        for claim in FORBIDDEN_CLAIMS:
            if claim in text:
                offenders.append(f"{relative}: {claim!r}")
        for match in re.finditer(r"HIPAA compliant", text):
            start = max(0, match.start() - 4)
            end = min(len(text), match.end() + 4)
            window = text[start:end]
            # The approved banner says "not HIPAA compliant yet".
            if "not HIPAA compliant yet" not in text[max(0, match.start() - 8) : match.end() + 4]:
                offenders.append(f"{relative}: unprotected {window!r}")
    assert offenders == []
