"""S3 "no telemetry": shipped source makes no calls to non-loopback hosts.

Scans the backend package and the SPA source (TS/TSX/CSS/HTML) for http(s)
URLs. Only loopback hosts are allowed; a remote URL (analytics, CDN, web
fonts) would also be blocked by the strict CSP at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
SCANNED = [
    (REPO / "psychtool", ("*.py",)),
    (REPO / "web" / "src", ("*.ts", "*.tsx", "*.css", "*.html")),
]
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
URL_RE = re.compile(r"https?://[^\s'\"`<>()]+")


def _source_files():
    for root, patterns in SCANNED:
        for pattern in patterns:
            yield from root.rglob(pattern)
    yield REPO / "web" / "index.html"


def test_no_remote_urls_in_shipped_source():
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8-sig")
        for match in URL_RE.finditer(text):
            host = urlsplit(match.group(0)).hostname
            if host not in ALLOWED_HOSTS:
                offenders.append(f"{path.relative_to(REPO)}: {match.group(0)}")
    assert offenders == []


def test_scanner_catches_a_remote_url(tmp_path):
    sample = "@import url('https://fonts.googleapis.com/css2?family=X');"
    hosts = [urlsplit(m.group(0)).hostname for m in URL_RE.finditer(sample)]
    assert hosts == ["fonts.googleapis.com"]
