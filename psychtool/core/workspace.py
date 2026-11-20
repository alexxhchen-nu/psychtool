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
) -> Material:
    workspace = Path(workspace)
    meta = json.loads(_meta_path(workspace).read_text(encoding="utf-8"))
    case_id = meta["case_id"]
    version = latest_version(workspace, material_id) + 1
    material = Material(
        id=material_id,
        case_id=case_id,
        version=version,
        title=title,
        provider=provider,
        date=date,
        passages=_split_passages(text),
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
