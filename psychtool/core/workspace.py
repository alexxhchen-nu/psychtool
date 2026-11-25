"""Workspace and material storage (version-immutable, no network, no presentation).

ADR 0005: a workspace is a directory; materials are versioned JSON files.
Locator for a passage = document version + passage id.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

META_FILENAME = "meta.json"
SUBDIRS = ("materials", "claims", "drafts", "reviews", "egress")
IDENTIFIERS_FILENAME = "identifiers.json"


class WorkspaceExistsError(RuntimeError):
    """Raised when initialising a workspace that already exists."""


class Passage(BaseModel):
    id: str
    text: str


class Material(BaseModel):
    id: str
    case_id: str
    version: int = 1
    title: str
    provider: str
    date: str
    passages: list[Passage]
    # ADR 0016: 'case' (clinical source material, the default everywhere) or
    # 'dims' (her uploaded dimension list — never an evidence source).
    kind: str = "case"

    @field_validator("provider")
    @classmethod
    def _provider_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("provider must not be empty")
        return v.strip()


def _meta_path(workspace: Path) -> Path:
    return workspace / META_FILENAME


def _split_passages(text: str) -> list[Passage]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text)]
    blocks = [b for b in blocks if b]
    return [Passage(id=f"p{i:03d}", text=b) for i, b in enumerate(blocks, start=1)]


def split_passages(text: str) -> list[Passage]:
    """Public alias: split raw text into versioned passage blocks."""
    return _split_passages(text)


def split_dimension_lines(text: str) -> list[Passage]:
    """Split a dimension list into one passage per non-empty line.

    The prototype treats each list line as its own paragraph (so
    "Source: your list, paragraph n" can point at that line). Case
    materials still use blank-line blocks via :func:`split_passages`.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [Passage(id=f"p{i:03d}", text=line) for i, line in enumerate(lines, start=1)]


def init_workspace(workspace: Path, *, case_id: str) -> Path:
    workspace = Path(workspace)
    if workspace.exists():
        raise WorkspaceExistsError(f"workspace already exists: {workspace}")
    workspace.mkdir(parents=True)
    for sub in SUBDIRS:
        (workspace / sub).mkdir()
    meta = {
        "case_id": case_id,
        "data_tier": "synthetic",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _meta_path(workspace).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return workspace


def latest_version(workspace: Path, material_id: str) -> int:
    materials = workspace / "materials"
    if not materials.is_dir():
        return 0
    versions = []
    for f in materials.glob(f"{material_id}.v*.json"):
        m = re.match(rf"^{re.escape(material_id)}\.v(\d+)\.json$", f.name)
        if m:
            versions.append(int(m.group(1)))
    return max(versions, default=0)


def import_material(
    workspace: Path,
    *,
    material_id: str,
    title: str,
    provider: str,
    date: str,
    text: str,
    blocked_out: list[int] | None = None,
) -> Material:
    """Write one versioned material, screening protected content first (R13).

    Blocked passages are dropped and the kept ones renumbered from ``p001``
    (a fresh JSON version has no claims yet, so renumbering is safe); the
    number of dropped paragraphs is appended to ``blocked_out`` when given.
    Raises ``ProtectedContentError("protected_content")`` when every passage
    is blocked and ``ProtectedContentError("protected_check_failed")`` when
    the screen itself errors — in both cases nothing is written.
    """
    from psychtool.core.protected import (
        PROTECTED_CONTENT_REASON,
        ProtectedContentError,
        filter_protected_passages,
    )

    workspace = Path(workspace)
    meta = json.loads(_meta_path(workspace).read_text(encoding="utf-8"))
    case_id = meta["case_id"]
    passages, blocked_count, _ = filter_protected_passages(_split_passages(text))
    if not passages:
        raise ProtectedContentError(PROTECTED_CONTENT_REASON)
    if blocked_out is not None:
        blocked_out.append(blocked_count)
    version = latest_version(workspace, material_id) + 1
    material = Material(
        id=material_id,
        case_id=case_id,
        version=version,
        title=title,
        provider=provider,
        date=date,
        passages=passages,
    )
    out = workspace / "materials" / f"{material_id}.v{version}.json"
    out.write_text(material.model_dump_json(indent=2), encoding="utf-8")
    return material


def list_materials(workspace: Path) -> list[Material]:
    materials = workspace / "materials"
    if not materials.is_dir():
        return []
    latest: dict[str, int] = {}
    for f in materials.glob("*.v*.json"):
        m = re.match(r"^(.+)\.v(\d+)\.json$", f.name)
        if not m:
            continue
        material_id, ver = m.group(1), int(m.group(2))
        if material_id not in latest or ver > latest[material_id]:
            latest[material_id] = ver
    return [
        Material.model_validate_json(
            (materials / f"{mid}.v{ver}.json").read_text(encoding="utf-8")
        )
        for mid, ver in sorted(latest.items())
    ]


def set_known_names(workspace: Path, names: list[str]) -> tuple[str, ...]:
    """Persist the caller-supplied names used for identifier redaction.

    These are the human-entered identifying values (e.g. ``client_name`` and
    ``evaluator_name`` template fields); redaction uses them as the
    highest-confidence name list without sending them to a model.
    """
    workspace = Path(workspace)
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        name = name.strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            deduped.append(name)
    deduped.sort(key=str.lower)
    deduped = tuple(deduped)
    (workspace / IDENTIFIERS_FILENAME).write_text(
        json.dumps(list(deduped), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return deduped


def get_known_names(workspace: Path) -> tuple[str, ...]:
    path = Path(workspace) / IDENTIFIERS_FILENAME
    if not path.is_file():
        return ()
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(data) if isinstance(data, list) else ()
