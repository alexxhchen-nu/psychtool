"""Reviewable claim suggestions from versioned intake passages."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from psychtool.core.claims import Claim, ProviderRole, add_claim, get_claim
from psychtool.core.workspace import Material, list_materials


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


def _material(workspace: Path, material_id: str) -> Material:
    for material in list_materials(workspace):
        if material.id == material_id:
            return material
    raise KeyError(f"unknown material: {material_id}")


def suggest_claims(
    workspace: Path,
    material_id: str,
    *,
    provider_role: ProviderRole,
    observation_setting: str = "intake",
) -> list[ClaimSuggestion]:
    """One literal candidate per passage; never infer diagnosis or chronology."""
    if provider_role not in ("self_report", "other_report", "clinician_interpretation"):
        raise ValueError("unknown provider role")
    material = _material(workspace, material_id)
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


def accept_suggestion(workspace: Path, suggestion: ClaimSuggestion) -> Claim:
    material = _material(workspace, suggestion.source_document_id)
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
        get_claim(workspace, suggestion.id)
    except KeyError:
        pass
    else:
        raise ValueError("claim already exists")
    return add_claim(
        workspace,
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
