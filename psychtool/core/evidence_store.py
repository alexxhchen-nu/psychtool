"""Shared sentence-evidence identity and JSON-workspace persistence (ADR 0017).

The stable evidence id is derived from the evidence's *location only*
(case, material, material version, passage, code-point span) — never from
rules, categories or quotes — so the SQLite store (schema v5+, ADR 0015) and
the ADR 0005 JSON workspace compute the same id for the same sentence.

The SQLite store persists evidence in its ``evidence`` table; this module
gives the file-workspace path the same guarantee: candidates produced by the
existing extractor are verified verbatim, persisted under ``evidence/`` in
the workspace, and only those stored ids may be cited by claim suggestions.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from psychtool.core.extract import EvidenceCandidate, Extractor, extract_evidence
from psychtool.core.workspace import Material

EVIDENCE_DIR = "evidence"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def evidence_id(
    case_id: str,
    material_id: str,
    material_version: int,
    passage_id: str,
    start: int,
    end: int,
) -> str:
    """Stable id derived from the location only (never rules/category)."""
    payload = "\x1f".join(
        (case_id, material_id, str(material_version), passage_id, str(start), str(end))
    )
    return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _evidence_dir(workspace: Path) -> Path:
    return Path(workspace) / EVIDENCE_DIR


def _material_evidence_path(workspace: Path, material_id: str, version: int) -> Path:
    if not _SAFE_ID_RE.fullmatch(material_id):
        raise ValueError("material id must be a short anonymous slug")
    return _evidence_dir(workspace) / f"{material_id}.v{version}.json"


def load_material_evidence(
    workspace: Path, material_id: str, version: int
) -> list[dict]:
    """Persisted evidence rows for one exact material version (possibly [])."""
    path = _material_evidence_path(workspace, material_id, version)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def ensure_material_evidence(
    workspace: Path,
    case_id: str,
    material: Material,
    extractor: Extractor,
) -> list[dict]:
    """Return the stored active evidence rows for one material version.

    Existing rows are returned as-is (the caller's stored set is the source
    of truth — re-running the extractor is never a substitute). When nothing
    is stored yet, the extractor's candidates are verified verbatim (never
    repaired), assigned their stable location-derived ids, persisted, and
    returned. Rows carry status ``active``; JSON workspaces do not supersede
    rows in this chunk.
    """
    workspace = Path(workspace)
    existing = load_material_evidence(workspace, material.id, material.version)
    if existing:
        return [row for row in existing if row.get("status") == "active"]
    result = extract_evidence(extractor, [material])
    rows = [
        {
            "evidence_id": evidence_id(
                case_id,
                item.span.material_id,
                item.span.material_version,
                item.span.passage_id,
                item.span.start,
                item.span.end,
            ),
            "material_id": item.span.material_id,
            "material_version": item.span.material_version,
            "passage_id": item.span.passage_id,
            "start": item.span.start,
            "end": item.span.end,
            "quote": item.quote,
            "status": "active",
        }
        for item in result.items
    ]
    directory = _evidence_dir(workspace)
    directory.mkdir(exist_ok=True)
    _material_evidence_path(workspace, material.id, material.version).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return rows


def active_evidence_by_passage(
    rows: list[dict],
) -> dict[str, list[str]]:
    """Map passage_id -> sorted active evidence ids (passages with none omitted)."""
    by_passage: dict[str, list[str]] = {}
    for row in rows:
        if row.get("status") != "active":
            continue
        by_passage.setdefault(row["passage_id"], []).append(row["evidence_id"])
    return {
        passage_id: sorted(ids) for passage_id, ids in by_passage.items() if ids
    }


def stored_evidence_quotes(
    workspace: Path, material_id: str, version: int, evidence_ids: list[str]
) -> list[str]:
    """Quotes of the given stored ids, for protected-content screening.

    Unknown ids are skipped here (existence is validated by accept_suggestion
    / the store before this is ever reached); screening only needs the text
    of ids that resolve.
    """
    rows = load_material_evidence(workspace, material_id, version)
    wanted = set(evidence_ids)
    return [row["quote"] for row in rows if row["evidence_id"] in wanted]
