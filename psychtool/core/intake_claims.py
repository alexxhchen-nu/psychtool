"""Reviewable claim suggestions from versioned intake passages."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Union

from pydantic import BaseModel

from psychtool.core.claims import Claim, ProviderRole, add_claim, get_claim
from psychtool.core.workspace import Material, list_materials

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.store.sqlite_store import CaseStore

# A JSON workspace directory, or one case bound inside the SQLite store.
WorkspaceTarget = Union[Path, str, "CaseStore"]


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


def suggest_claims(
    target: WorkspaceTarget,
    material_id: str,
    *,
    provider_role: ProviderRole,
    observation_setting: str = "intake",
) -> list[ClaimSuggestion]:
    """One literal candidate per passage; never infer diagnosis or chronology."""
    if provider_role not in ("self_report", "other_report", "clinician_interpretation"):
        raise ValueError("unknown provider role")
    material = _material(target, material_id)
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
        )
        for passage in material.passages
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
    )
