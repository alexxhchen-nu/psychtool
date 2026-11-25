"""Load an ADR 0005 JSON workspace directory for import into SQLite.

Read-only: this module never writes to the workspace directory. It validates
the on-disk layout and returns plain data bundles; ``SqliteStore`` decides how
to persist them. Nothing here touches the network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from psychtool.core.claims import Claim
from psychtool.core.sections import SectionDraft
from psychtool.core.workspace import Material

_VERSIONED_FILE = re.compile(r"^(.+)\.v(\d+)\.json$")


def _read_versioned(directory: Path, model):
    """Latest version of each entity in one JSON directory, id-sorted."""
    if not directory.is_dir():
        return []
    latest: dict[str, int] = {}
    for path in directory.glob("*.v*.json"):
        match = _VERSIONED_FILE.match(path.name)
        if not match:
            continue
        entity_id, version = match.group(1), int(match.group(2))
        if entity_id not in latest or version > latest[entity_id]:
            latest[entity_id] = version
    return [
        model.model_validate_json(
            (directory / f"{entity_id}.v{version}.json").read_text(encoding="utf-8")
        )
        for entity_id, version in sorted(latest.items())
    ]


def _read_all_versions(directory: Path, model):
    """Every version of every entity (imports keep full version history)."""
    if not directory.is_dir():
        return []
    entities = []
    for path in sorted(directory.glob("*.v*.json")):
        match = _VERSIONED_FILE.match(path.name)
        if not match:
            continue
        entities.append(model.model_validate_json(path.read_text(encoding="utf-8")))
    return entities


def read_json_workspace(workspace: Path) -> dict:
    """Parse one JSON workspace directory into an importable bundle.

    Raises ``ValueError``/``FileNotFoundError`` on any malformed content so the
    caller can abort the whole import before writing a single row.
    """
    workspace = Path(workspace)
    meta_path = workspace / "meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"no meta.json in {workspace}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    case_id = meta.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("workspace meta.json has no case_id")
    data_tier = meta.get("data_tier", "synthetic")
    if data_tier != "synthetic":
        # M1 milestone is synthetic-only: a workspace marked "real" (or any
        # unknown tier) must never reach the app store. Abort before writing.
        raise ValueError(
            f"import-json only accepts synthetic workspaces; meta.json data_tier is {data_tier!r}"
        )
    created_at = meta.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("workspace meta.json has no created_at")

    names_path = workspace / "identifiers.json"
    known_names: list[str] = []
    if names_path.is_file():
        raw_names = json.loads(names_path.read_text(encoding="utf-8"))
        if isinstance(raw_names, list):
            known_names = [str(name) for name in raw_names]

    materials = _read_all_versions(workspace / "materials", Material)
    claims = _read_all_versions(workspace / "claims", Claim)
    sections: list[SectionDraft] = []
    sections_root = workspace / "sections"
    if sections_root.is_dir():
        for template_dir in sorted(p for p in sections_root.iterdir() if p.is_dir()):
            sections.extend(_read_all_versions(template_dir, SectionDraft))

    # Materials and claims carry their own case_id; refuse a mixed workspace
    # rather than silently rebinding foreign rows.
    for entity in (*materials, *claims, *sections):
        if entity.case_id != case_id:
            raise ValueError(
                f"entity {getattr(entity, 'id', entity.section_id)!r} belongs to "
                f"case {entity.case_id!r}, not {case_id!r}"
            )

    return {
        "case_id": case_id,
        "data_tier": data_tier,
        "created_at": created_at,
        "known_names": known_names,
        "materials": materials,
        "claims": claims,
        "sections": sections,
    }
