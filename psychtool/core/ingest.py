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

from psychtool.core.protected import find_protected
from psychtool.core.redact import find_identifiers, redact_text
from psychtool.core.workspace import Material, Passage, get_known_names, import_material, split_passages

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

# Fixed R13 rejection vocabulary (ADR 0013). The message never quotes the
# filename, the title, or any blocked text; the count is filled in by the
# client from ``blocked_paragraphs``.
PROTECTED_CONTENT_REASON = "protected_content"
PROTECTED_CHECK_FAILED_REASON = "protected_check_failed"
PROTECTED_CONTENT_MESSAGE = (
    "Paragraphs were held back: they appear to contain test items, norms or "
    "scoring rules. They were not added to this case and will never be sent "
    "to the AI assistant. A way to request release will come in a later version."
)
PROTECTED_CHECK_FAILED_MESSAGE = (
    "The upload could not be checked for protected test content, so it was "
    "rejected. Nothing was stored. Try again; if it keeps failing, contact support."
)


class ProtectedContentError(ValueError):
    """An R13 upload rejection: an allowlisted ``reason`` plus fixed text."""

    def __init__(self, reason: str) -> None:
        if reason not in (PROTECTED_CONTENT_REASON, PROTECTED_CHECK_FAILED_REASON):
            raise ValueError(f"unknown protected-content reason: {reason!r}")
        self.reason = reason
        message = (
            PROTECTED_CONTENT_MESSAGE
            if reason == PROTECTED_CONTENT_REASON
            else PROTECTED_CHECK_FAILED_MESSAGE
        )
        super().__init__(message)


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


def _filter_protected_passages(passages: list[Passage]) -> tuple[list[Passage], int, str | None]:
    """Drop passages matching the R13 screen; fail closed on any checker error.

    Kept passages are renumbered contiguously from ``p001`` so stored passage
    ids and positions always line up with the text actually stored (quotes and
    char ranges are computed against the stored text). Returns
    ``(kept, blocked_count, blocked_hash)`` where the hash is sha256 of the
    blocked passages' text joined with ``"\\n\\n"`` (None when nothing blocked).
    """
    import hashlib

    try:
        blocked_indexes = find_protected([passage.text for passage in passages])
    except Exception:
        # Fail closed (R13-AC2): a checker that errors rejects the whole
        # upload; nothing is written, not even an audit row.
        raise ProtectedContentError(PROTECTED_CHECK_FAILED_REASON) from None
    if not blocked_indexes:
        return passages, 0, None
    blocked = set(blocked_indexes)
    kept = [
        Passage(id=f"p{position:03d}", text=passage.text)
        for position, passage in enumerate(
            (p for i, p in enumerate(passages) if i not in blocked), start=1
        )
    ]
    blocked_hash = hashlib.sha256(
        "\n\n".join(passages[i].text for i in blocked_indexes).encode("utf-8")
    ).hexdigest()
    return kept, len(blocked_indexes), blocked_hash


def import_upload(target: UploadTarget, *, filename: str, data: bytes,
                  material_id: str, title: str, provider: str, date: str) -> tuple[Material, list[dict], int]:
    """Import one upload, dropping protected passages before any store write.

    Returns ``(material, identifier_findings, blocked_count)``. Raises
    :class:`ProtectedContentError` when every passage is blocked
    (``protected_content``) or the check itself fails
    (``protected_check_failed``); in both cases nothing is written except the
    block audit row for the all-blocked case (ADR 0013).
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", material_id):
        raise ValueError("material id must be a short anonymous slug")
    text = parse_upload(filename, data)
    passages, blocked_count, blocked_hash = _filter_protected_passages(
        split_passages(text)
    )
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
            blocked_count=blocked_count, blocked_hash=blocked_hash,
        )
        return material, [{"category": hit["category"], "label": hit["label"]}
                          for hit in findings], blocked_count
    workspace = Path(target)
    names = get_known_names(workspace)
    kept_text = "\n\n".join(passage.text for passage in passages)
    findings = find_identifiers(kept_text, known_names=names)
    safe_title, _ = redact_text(title, known_names=names)
    safe_provider, _ = redact_text(provider, known_names=names)
    safe_date, _ = redact_text(date, known_names=names)
    if not passages:
        raise ProtectedContentError(PROTECTED_CONTENT_REASON)
    material = import_material(workspace, material_id=material_id, title=safe_title,
                               provider=safe_provider, date=safe_date, text="\n\n".join(
                                   passage.text for passage in passages))
    return material, [{"category": hit["category"], "label": hit["label"]}
                      for hit in findings], blocked_count
