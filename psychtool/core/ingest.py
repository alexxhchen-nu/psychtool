"""Local-only document parsing before material import or model access.

Two entry points:

- :func:`parse_upload` — the CLI path, which may run local Indra OCR for
  PDF/images (unchanged since ADR 0005-era ingest);
- :func:`parse_server_upload` — the server/browser path (ADR 0012), which
  accepts only UTF-8 ``.txt``/``.md`` and rejects everything else with a
  fixed ``(reason, message)`` pair. It never runs OCR and its messages never
  quote the filename or the content.

R13 (ADR 0013): every upload — server file upload, server paste, and the
shared :func:`import_upload` choke point — is screened for protected test
content before anything is stored. Blocked passages never reach the material
store; if the screen itself errors the whole upload is rejected (fail-closed).
"""

from __future__ import annotations

import tempfile
import re
from pathlib import Path
from typing import TYPE_CHECKING, Union

from psychtool.core.protected import (
    PROTECTED_CHECK_FAILED_MESSAGE,
    PROTECTED_CHECK_FAILED_REASON,
    PROTECTED_CONTENT_MESSAGE,
    PROTECTED_CONTENT_REASON,
    ProtectedContentError,
    filter_protected_passages as _filter_protected_passages,
    find_protected,
)
from psychtool.core.redact import find_identifiers, redact_text
from psychtool.core.workspace import Material, Passage, get_known_names, import_material, split_dimension_lines, split_passages

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

# R13 rejection vocabulary and the shared passage filter live in
# ``psychtool.core.protected`` (ADR 0013); they are re-imported above so
# existing callers keep working: PROTECTED_CONTENT_REASON,
# PROTECTED_CHECK_FAILED_REASON, PROTECTED_CONTENT_MESSAGE,
# PROTECTED_CHECK_FAILED_MESSAGE, ProtectedContentError, _filter_protected_passages.


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
                  material_id: str, title: str, provider: str, date: str,
                  kind: str = "case") -> tuple[Material, list[dict], int]:
    """Import one upload, dropping protected passages before any store write.

    Returns ``(material, identifier_findings, blocked_count)``. Raises
    :class:`ProtectedContentError` when every passage is blocked
    (``protected_content``) or the check itself fails
    (``protected_check_failed``); in both cases nothing is written except the
    block audit row for the all-blocked case (ADR 0013).

    ``kind`` is ``'case'`` for clinical source materials and ``'dims'`` for
    her uploaded dimension list (ADR 0016); the JSON-workspace (CLI) branch
    only ever receives ``'case'``.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", material_id):
        raise ValueError("material id must be a short anonymous slug")
    text = parse_upload(filename, data)
    blocks = split_dimension_lines(text) if kind == "dims" else split_passages(text)
    passages, blocked_count, blocked_hash = _filter_protected_passages(blocks)
    if _is_case_store(target):
        names = target.get_known_names()
        # Findings are computed over the KEPT passages only: nothing about
        # blocked passages may leak into the response (ADR 0013).
        kept_text = "\n\n".join(passage.text for passage in passages)
        findings = find_identifiers(kept_text, known_names=names)
        safe_title, _ = redact_text(title, known_names=names)
        safe_provider, _ = redact_text(provider, known_names=names)
        safe_date, _ = redact_text(date, known_names=names)
        # Redact only the passages that survived the screen; blocked text is
        # never stored, so it is never redacted for storage either.
        safe_passages = [
            Passage(id=passage.id, text=redact_text(passage.text, known_names=names)[0])
            for passage in passages
        ]
        if not safe_passages:
            # All-blocked: no material row, but the block itself is audited
            # (its own transaction, ADR 0011/0013).
            target.append_audit(
                case_id=target.case_id,
                action="material.protected_blocked",
                object_type="material",
                object_id=material_id,
                content_hash=blocked_hash,
                item_count=blocked_count,
            )
            raise ProtectedContentError(PROTECTED_CONTENT_REASON)
        material = target.import_material(
            material_id=material_id, title=safe_title, provider=safe_provider,
            date=safe_date, passages=safe_passages,
            blocked_count=blocked_count, blocked_hash=blocked_hash, kind=kind,
        )
        return material, [{"category": hit["category"], "label": hit["label"]}
                          for hit in findings], blocked_count
    workspace = Path(target)
    names = get_known_names(workspace)
    if not passages:
        # All-blocked in the JSON branch: nothing is written (no audit row in
        # the JSON store), so reject with the fixed reason.
        raise ProtectedContentError(PROTECTED_CONTENT_REASON)
    kept_text = "\n\n".join(passage.text for passage in passages)
    findings = find_identifiers(kept_text, known_names=names)
    safe_title, _ = redact_text(title, known_names=names)
    safe_provider, _ = redact_text(provider, known_names=names)
    safe_date, _ = redact_text(date, known_names=names)
    # The screen inside ``workspace.import_material`` re-runs on the kept
    # passages and finds nothing (the filter is deterministic), so the count
    # returned here stays the count computed above.
    material = import_material(workspace, material_id=material_id, title=safe_title,
                               provider=safe_provider, date=safe_date, text="\n\n".join(
                                   passage.text for passage in passages))
    return material, [{"category": hit["category"], "label": hit["label"]}
                      for hit in findings], blocked_count
