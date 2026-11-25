"""Source invalidation and review summary.

When a source material is re-imported at a newer version, claims citing the old
version become stale: their verification status must not carry forward, and
their old locator remains readable but is no longer treated as current.
"""

from __future__ import annotations

from pathlib import Path

from psychtool.core.egress_store import JsonDirStore
from psychtool.core.workspace import latest_version
from psychtool.core.claims import Claim, get_claim, list_claims, mark_status
from psychtool.core.draft import list_drafts, load_draft
from psychtool.core.egress import (
    EgressStaleError,
    EgressTarget,
    SourceRef,
    _as_egress_store,
    _invalidate_request_locked,
    _request_transition_lock,
    get_egress_request,
)


def _latest_material_version(target: EgressTarget, material_id: str) -> int:
    store = _as_egress_store(target)
    if isinstance(store, JsonDirStore):
        return latest_version(store.workspace, material_id)
    return store.latest_material_version(material_id)  # type: ignore[attr-defined]


def _get_claim(target: EgressTarget, claim_id: str) -> Claim:
    store = _as_egress_store(target)
    if isinstance(store, JsonDirStore):
        return get_claim(store.workspace, claim_id)
    return store.get_claim(claim_id)  # type: ignore[attr-defined]


def _load_draft(target: EgressTarget, draft_id: str):
    store = _as_egress_store(target)
    if isinstance(store, JsonDirStore):
        return load_draft(store.workspace, draft_id)
    return store.get_draft(draft_id)  # type: ignore[attr-defined]


def validate_source_refs(target: EgressTarget, refs: list[SourceRef]) -> None:
    """Raise when any source reference is missing or no longer the latest version."""
    for ref in refs:
        try:
            if ref.kind == "claim":
                claim = _get_claim(target, ref.id)
                current_version = claim.version
            elif ref.kind == "material":
                current_version = _latest_material_version(target, ref.id)
            else:
                current_version = _load_draft(target, ref.id).version
        except (FileNotFoundError, KeyError):
            raise EgressStaleError("egress source reference is stale") from None
        if current_version == 0 or current_version != ref.version:
            raise EgressStaleError("egress source reference is stale")
        if ref.kind == "claim":
            material_version = _latest_material_version(target, claim.source_document_id)
            if material_version == 0 or material_version != claim.source_version:
                raise EgressStaleError("egress source reference is stale")


def validate_request_sources(target: EgressTarget, request_id: str) -> None:
    """Validate a persisted request's sources, invalidating it on failure."""
    with _request_transition_lock(target, request_id):
        request = get_egress_request(target, request_id)
        try:
            validate_source_refs(target, request.source_refs)
        except EgressStaleError:
            _invalidate_request_locked(target, request_id)
            raise


def find_stale_claims(workspace: Path) -> list[Claim]:
    claims = list_claims(workspace)
    stale: list[Claim] = []
    for c in claims:
        current = latest_version(workspace, c.source_document_id)
        if c.source_version != current:
            stale.append(c)
    return stale


def reopen_stale_claims(workspace: Path) -> int:
    """Void the confirmation of every stale claim; returns how many changed."""
    n = 0
    for c in find_stale_claims(workspace):
        if c.verification_status != "pending":
            mark_status(workspace, c.id, "pending")
            n += 1
    return n


def find_conflicts(workspace: Path) -> dict[str, list[Claim]]:
    claims = list_claims(workspace)
    by_topic: dict[str, list[Claim]] = {}
    for c in claims:
        by_topic.setdefault(c.topic, []).append(c)
    return {t: cs for t, cs in by_topic.items() if len({c.text for c in cs}) > 1}


def stale_drafts(workspace: Path) -> list[str]:
    stale_ids = {c.id for c in find_stale_claims(workspace)}
    if not stale_ids:
        return []
    return [d.id for d in list_drafts(workspace) if set(d.claim_ids) & stale_ids]


def review_summary(workspace: Path) -> dict:
    return {
        "stale_claims": [c.id for c in find_stale_claims(workspace)],
        "conflicts": {t: [c.id for c in cs] for t, cs in find_conflicts(workspace).items()},
        "pending": [c.id for c in list_claims(workspace) if c.verification_status == "pending"],
        "stale_drafts": stale_drafts(workspace),
    }
