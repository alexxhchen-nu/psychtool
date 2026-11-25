"""Reviewable claim suggestions from stored sentence evidence (ADR 0017).

Sentence evidence is the only source a claim cites. A suggestion exists for a
passage only when that passage has at least one stored *active* evidence row
for the exact material version, and the suggestion carries those evidence ids.
The paragraph locator (document + version + passage) stays as the grouping
the clinician reviews, but it is no longer the source of truth — the evidence
ids are.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Union

from pydantic import BaseModel

from psychtool.core.claims import Claim, ProviderRole, add_claim, get_claim
from psychtool.core.evidence_store import (
    active_evidence_by_passage,
    ensure_material_evidence,
    load_material_evidence,
)
from psychtool.core.extract import RuleExtractor
from psychtool.core.workspace import Material, list_materials

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.store.sqlite_store import CaseStore

# A JSON workspace directory, or one case bound inside the SQLite store.
WorkspaceTarget = Union[Path, str, "CaseStore"]

# Fixed message for any evidence-id problem at accept time: it must not
# reveal whether an id exists on another case.
INVALID_EVIDENCE_IDS = "invalid evidence ids"


class ClaimSuggestion(BaseModel):
    id: str
    source_document_id: str
    source_version: int
    source_passage_id: str
    source_text: str
    text: str
    provider_role: ProviderRole
    observation_setting: str
    record_time: str
    event_time: str | None = None
    category: str = "source_statement"
    topic: str = "general"
    # Sentence-level evidence ids this suggestion cites (schema v7 / ADR
    # 0017). Never empty on a produced suggestion; accept re-validates.
    evidence_ids: list[str] = []


def _is_case_store(target: object) -> bool:
    return not isinstance(target, (str, Path))


def _material(target: WorkspaceTarget, material_id: str) -> Material:
    if _is_case_store(target):
        return target.get_material(material_id)
    for material in list_materials(Path(target)):
        if material.id == material_id:
            return material
    raise KeyError(f"unknown material: {material_id}")


def _existing_claim(target: WorkspaceTarget, claim_id: str) -> Claim:
    if _is_case_store(target):
        return target.get_claim(claim_id)
    return get_claim(Path(target), claim_id)


def _add_claim(target: WorkspaceTarget, *, claim_id: str, **fields) -> Claim:
    if _is_case_store(target):
        return target.add_claim(claim_id=claim_id, **fields)
    return add_claim(Path(target), claim_id=claim_id, **fields)


def _case_id(target: WorkspaceTarget) -> str:
    if _is_case_store(target):
        return target.case_id
    import json

    meta = json.loads((Path(target) / "meta.json").read_text(encoding="utf-8"))
    return meta["case_id"]


def _evidence_by_passage(target: WorkspaceTarget, material: Material) -> dict[str, list[str]]:
    """Stored active evidence ids per passage for this exact material version.

    CaseStore: reads already-persisted rows (upload auto-extracts); it never
    re-extracts as a substitute for stored rows. File workspace: if nothing is
    stored yet, the existing RuleExtractor runs once, the verbatim-verified
    candidates are persisted with their stable ids, and those stored ids are
    used from then on.
    """
    if _is_case_store(target):
        return target.active_evidence_ids_by_passage(material.id, material.version)
    rows = ensure_material_evidence(
        Path(target), _case_id(target), material, RuleExtractor()
    )
    return active_evidence_by_passage(rows)


def _stored_evidence_ids(target: WorkspaceTarget, material: Material) -> set[str]:
    """Every stored evidence id for this material version (any status).

    CaseStore reads the already-persisted rows directly (no re-extraction).
    """
    if _is_case_store(target):
        return set(target.evidence_ids_for_material(material.id, material.version))
    rows = load_material_evidence(Path(target), material.id, material.version)
    return {row["evidence_id"] for row in rows}


def suggest_claims(
    target: WorkspaceTarget,
    material_id: str,
    *,
    provider_role: ProviderRole,
    observation_setting: str = "intake",
) -> list[ClaimSuggestion]:
    """One candidate per passage with stored active sentence evidence.

    A passage with no stored sentence evidence produces no suggestion; no
    suggestion ever has empty evidence_ids. Never infer diagnosis or
    chronology — the text is the passage text the clinician reviews.
    """
    if provider_role not in ("self_report", "other_report", "clinician_interpretation"):
        raise ValueError("unknown provider role")
    material = _material(target, material_id)
    by_passage = _evidence_by_passage(target, material)
    return [
        ClaimSuggestion(
            id=f"{material.id}-v{material.version}-{passage.id}",
            source_document_id=material.id,
            source_version=material.version,
            source_passage_id=passage.id,
            source_text=passage.text,
            text=passage.text,
            provider_role=provider_role,
            observation_setting=observation_setting,
            record_time=material.date,
            evidence_ids=by_passage[passage.id],
        )
        for passage in material.passages
        if passage.id in by_passage
    ]


def accept_suggestion(target: WorkspaceTarget, suggestion: ClaimSuggestion) -> Claim:
    material = _material(target, suggestion.source_document_id)
    if material.version != suggestion.source_version:
        raise ValueError("source material version changed; refresh suggestions")
    source = next((p for p in material.passages if p.id == suggestion.source_passage_id), None)
    if source is None or source.text != suggestion.source_text:
        raise ValueError("source passage changed; refresh suggestions")
    expected_id = f"{material.id}-v{material.version}-{source.id}"
    if suggestion.id != expected_id:
        raise ValueError("suggestion id does not match source")
    if suggestion.record_time != material.date:
        raise ValueError("record time does not match source")
    # Sentence evidence is the only source: at least one id, and every id
    # must resolve to stored evidence in this case/material version. The
    # fixed message never reveals whether an id exists on another case.
    if not suggestion.evidence_ids:
        raise ValueError(INVALID_EVIDENCE_IDS)
    stored = _stored_evidence_ids(target, material)
    if any(evidence_id not in stored for evidence_id in suggestion.evidence_ids):
        raise ValueError(INVALID_EVIDENCE_IDS)
    try:
        _existing_claim(target, suggestion.id)
    except KeyError:
        pass
    else:
        raise ValueError("claim already exists")
    return _add_claim(
        target,
        claim_id=suggestion.id,
        source_document_id=material.id,
        source_version=material.version,
        source_passage_id=source.id,
        provider_role=suggestion.provider_role,
        observation_setting=suggestion.observation_setting,
        record_time=suggestion.record_time,
        event_time=suggestion.event_time,
        category=suggestion.category,
        topic=suggestion.topic,
        text=suggestion.text,
        evidence_ids=list(suggestion.evidence_ids),
    )
