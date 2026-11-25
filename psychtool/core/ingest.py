"""Local-only document parsing before material import or model access.

Two entry points:

- :func:`parse_upload` — the CLI path, which may run local Indra OCR for
  PDF/images (unchanged since ADR 0005-era ingest);
- :func:`parse_server_upload` — the server/browser path (ADR 0012), which
  accepts only UTF-8 ``.txt``/``.md`` and rejects everything else with a
  fixed ``(reason, message)`` pair. It never runs OCR and its messages never
  quote the filename or the content.
"""

from __future__ import annotations

import tempfile
import re
from pathlib import Path
from typing import TYPE_CHECKING, Union

from psychtool.core.redact import find_identifiers, redact_text
from psychtool.core.workspace import Material, get_known_names, import_material, split_passages

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.store.sqlite_store import CaseStore

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TEXT_SUFFIXES = {".txt", ".md"}
OCR_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}

# Fixed rejection vocabulary for the server upload path (ADR 0012). Every
# message is a constant: nothing user-supplied may ever be echoed back.
SCAN_NOT_SUPPORTED_MESSAGE = (
    "Scanned PDFs and images are not supported in this version. "
    "Upload a .txt or .md file."
)
SERVER_UPLOAD_MESSAGES = {
    "too_large": "The file is too large. The limit is 10 MiB (10,485,760 bytes).",
    "unsupported_type": "Only .txt and .md files are supported. Upload a .txt or .md file.",
    "scan_not_supported": SCAN_NOT_SUPPORTED_MESSAGE,
    "not_utf8": "The file is not valid UTF-8 text. Save it as UTF-8 and try again.",
    "empty": "The file contains no text.",
}
SCAN_SUFFIXES = OCR_SUFFIXES  # R12: scans/images rejected on the server, no OCR


class ServerUploadError(ValueError):
    """A server upload rejection: an allowlisted ``reason`` plus fixed text."""

    def __init__(self, reason: str) -> None:
        if reason not in SERVER_UPLOAD_MESSAGES:
            raise ValueError(f"unknown server upload reason: {reason!r}")
        self.reason = reason
        super().__init__(SERVER_UPLOAD_MESSAGES[reason])


def parse_server_upload(filename: str, data: bytes) -> str:
    """Decode one browser upload under the M1 server rules (ADR 0012).

    Only ``.txt``/``.md`` (UTF-8, optional BOM) pass; every other input is
    rejected before any store write. This function never invokes OCR.
    """
    if len(data) > MAX_UPLOAD_BYTES:
        raise ServerUploadError("too_large")
    suffix = Path(filename).suffix.lower()
    if suffix in SCAN_SUFFIXES:
        raise ServerUploadError("scan_not_supported")
    if suffix not in TEXT_SUFFIXES:
        raise ServerUploadError("unsupported_type")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ServerUploadError("not_utf8") from None
    if not text.strip():
        raise ServerUploadError("empty")
    return text

# A paste/upload target: a legacy JSON workspace directory, or one case bound
# inside the SQLite store (``psychtool.store.sqlite_store.CaseStore``).
UploadTarget = Union[Path, str, "CaseStore"]


def parse_upload(filename: str, data: bytes) -> str:
    """Parse text or run Indra locally; no model gateway receives the file."""
    suffix = Path(filename).suffix.lower()
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("file exceeds 10 MB limit")
    if suffix in TEXT_SUFFIXES:
        return data.decode("utf-8-sig")
    if suffix not in OCR_SUFFIXES:
        raise ValueError("unsupported file type")
    try:
        import indra_ocr
    except ImportError as exc:
        raise RuntimeError("Indra OCR is not installed on the server") from exc
    with tempfile.TemporaryDirectory(prefix="psychtool-ocr-") as temp_dir:
        source = Path(temp_dir) / f"upload{suffix}"
        source.write_bytes(data)
        converter = indra_ocr.load(threads=4)
        pages = [page.text for _, page in converter.convert(str(source))]
    if not pages or not any(page.strip() for page in pages):
        raise ValueError("document contains no readable text")
    return "\n\n".join(pages)


def _is_case_store(target: object) -> bool:
    return not isinstance(target, (str, Path))


def import_upload(target: UploadTarget, *, filename: str, data: bytes,
                  material_id: str, title: str, provider: str, date: str) -> tuple[Material, list[dict]]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", material_id):
        raise ValueError("material id must be a short anonymous slug")
    text = parse_upload(filename, data)
    if _is_case_store(target):
        names = target.get_known_names()
        findings = find_identifiers(text, known_names=names)
        safe_text, _ = redact_text(text, known_names=names)
        safe_title, _ = redact_text(title, known_names=names)
        safe_provider, _ = redact_text(provider, known_names=names)
        safe_date, _ = redact_text(date, known_names=names)
        material = target.import_material(
            material_id=material_id, title=safe_title, provider=safe_provider,
            date=safe_date, passages=split_passages(safe_text),
        )
        return material, [{"category": hit["category"], "label": hit["label"]}
                          for hit in findings]
    workspace = Path(target)
    names = get_known_names(workspace)
    findings = find_identifiers(text, known_names=names)
    safe_text, _ = redact_text(text, known_names=names)
    safe_title, _ = redact_text(title, known_names=names)
    safe_provider, _ = redact_text(provider, known_names=names)
    safe_date, _ = redact_text(date, known_names=names)
    material = import_material(workspace, material_id=material_id, title=safe_title,
                               provider=safe_provider, date=safe_date, text=safe_text)
    return material, [{"category": hit["category"], "label": hit["label"]}
                      for hit in findings]
