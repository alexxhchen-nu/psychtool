"""Local-only document parsing before material import or model access."""

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
