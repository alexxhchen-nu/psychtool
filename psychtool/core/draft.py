"""Draft prompt freezing, strict generation, budget limits, and source index."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel

from psychtool.core.claims import Claim
from psychtool.core.egress import EgressRunner, SourceRef, require_egress_runner

DRAFTS_DIR = "drafts"
TEMPLATE_NAME = "draft.txt"


class BudgetExceeded(RuntimeError):
    """Raised when a generation would exceed or cannot enforce a budget."""


_COST_ENFORCEMENT_UNSUPPORTED = (
    "strict egress runner does not support cost enforcement; remove max_cost"
)


class Citation(BaseModel):
    claim_id: str
    claim_version: int | None = None
    source_document_id: str
    source_version: int
    source_passage_id: str
    statement: str


class Draft(BaseModel):
    id: str
    case_id: str
    version: int = 1
    claim_ids: list[str]
    text: str
    citations: list[Citation]


def _template() -> str:
    return files("psychtool.templates").joinpath(TEMPLATE_NAME).read_text(encoding="utf-8")


def _claim_block(claim: Claim) -> str:
    return (
        f"[{claim.id}] 来源 {claim.source_document_id} v{claim.source_version} "
        f"段落 {claim.source_passage_id}；归属 {claim.provider_role}；"
        f"场景 {claim.observation_setting}；记录时间 {claim.record_time}\n"
        f"{claim.text}"
    )


def build_prompt(claims: list[Claim], *, instructions: str) -> str:
    blocks = "\n\n".join(_claim_block(c) for c in claims)
    return _template().format(instructions=instructions, claims_block=blocks)


@dataclass(frozen=True)
class FrozenDraftInput:
    """One immutable-in-memory claim snapshot used through draft persistence."""

    prompt: str
    claims: tuple[Claim, ...]
    source_refs: tuple[SourceRef, ...]


def freeze_draft_input(
    workspace: Path,
    *,
    claim_ids: list[str],
    instructions: str,
) -> FrozenDraftInput:
    """Freeze prompt claims once so model-time edits cannot change citations."""
    claims = tuple(select_claims(Path(workspace), claim_ids))
    return FrozenDraftInput(
        prompt=build_prompt(list(claims), instructions=instructions),
        claims=claims,
        source_refs=tuple(
            SourceRef(kind="claim", id=claim.id, version=claim.version)
            for claim in claims
        ),
    )


def build_draft_request_input(
    workspace: Path,
    *,
    claim_ids: list[str],
    instructions: str,
) -> tuple[str, list[SourceRef]]:
    """Build a prompt and refs from the same frozen claim snapshots."""
    frozen = freeze_draft_input(
        workspace,
        claim_ids=claim_ids,
        instructions=instructions,
    )
    return frozen.prompt, list(frozen.source_refs)


def _latest_version(dirpath: Path, draft_id: str) -> int:
    if not dirpath.is_dir():
        return 0
    versions = []
    for f in dirpath.glob(f"{draft_id}.v*.json"):
        m = re.match(rf"^{re.escape(draft_id)}\.v(\d+)\.json$", f.name)
        if m:
            versions.append(int(m.group(1)))
    return max(versions, default=0)


def _meta(workspace: Path) -> dict:
    return json.loads((workspace / "meta.json").read_text(encoding="utf-8"))


def _drafts_dir(workspace: Path) -> Path:
    return workspace / DRAFTS_DIR


def _is_case_store(target: object) -> bool:
    return not isinstance(target, (str, Path))


def select_claims(workspace: Path, claim_ids: list[str]) -> list[Claim]:
    from psychtool.core.claims import list_claims

    if _is_case_store(workspace):
        available = {c.id: c for c in workspace.list_claims()}
    else:
        available = {c.id: c for c in list_claims(Path(workspace))}
    missing = [cid for cid in claim_ids if cid not in available]
    if missing:
        raise KeyError(f"claims not in workspace: {missing}")
    # preserve requested order, de-duplicate
    seen: set[str] = set()
    selected: list[Claim] = []
    for cid in claim_ids:
        if cid not in seen:
            seen.add(cid)
            selected.append(available[cid])
    return selected


def validate_draft_budget(*, max_steps: int) -> None:
    if max_steps < 1:
        raise BudgetExceeded(f"max_steps must be >= 1, got {max_steps}")


def persist_generated_draft(
    workspace: Path,
    *,
    draft_id: str,
    frozen_input: FrozenDraftInput,
    text: str,
    max_steps: int = 1,
    max_cost: float | None = None,
    cost: float | None = None,
) -> Draft:
    """Persist text using only the claim snapshots that built its prompt."""
    workspace = Path(workspace)
    validate_draft_budget(max_steps=max_steps)
    if max_cost is not None and cost is not None and cost > max_cost:
        raise BudgetExceeded(f"cost {cost} exceeds max_cost {max_cost}")

    citations = [
        Citation(
            claim_id=claim.id,
            claim_version=claim.version,
            source_document_id=claim.source_document_id,
            source_version=claim.source_version,
            source_passage_id=claim.source_passage_id,
            statement=claim.text,
        )
        for claim in frozen_input.claims
    ]
    case_id = _meta(workspace)["case_id"]
    version = _latest_version(_drafts_dir(workspace), draft_id) + 1
    draft = Draft(
        id=draft_id,
        case_id=case_id,
        version=version,
        claim_ids=[claim.id for claim in frozen_input.claims],
        text=text,
        citations=citations,
    )
    out = _drafts_dir(workspace) / f"{draft_id}.v{version}.json"
    out.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    return draft


def generate_draft(
    workspace: Path,
    *,
    draft_id: str,
    claim_ids: list[str],
    instructions: str,
    runner: EgressRunner,
    max_steps: int = 1,
    max_cost: float | None = None,
) -> Draft:
    """Generate through a nominal egress runner and persist frozen provenance."""
    runner = require_egress_runner(runner)
    workspace = Path(workspace)
    if max_cost is not None:
        raise BudgetExceeded(_COST_ENFORCEMENT_UNSUPPORTED)
    validate_draft_budget(max_steps=max_steps)
    frozen = freeze_draft_input(
        workspace,
        claim_ids=claim_ids,
        instructions=instructions,
    )
    text = runner.run(
        workspace=workspace,
        prompt=frozen.prompt,
        purpose="draft_generation",
        source_refs=list(frozen.source_refs),
    )
    return persist_generated_draft(
        workspace,
        draft_id=draft_id,
        frozen_input=frozen,
        text=text,
        max_steps=max_steps,
        max_cost=max_cost,
    )


def load_draft(workspace: Path, draft_id: str) -> Draft:
    version = _latest_version(_drafts_dir(workspace), draft_id)
    if version == 0:
        raise KeyError(f"no draft with id {draft_id!r}")
    raw = (_drafts_dir(workspace) / f"{draft_id}.v{version}.json").read_text(encoding="utf-8")
    return Draft.model_validate_json(raw)


def list_drafts(workspace: Path) -> list[Draft]:
    d = _drafts_dir(workspace)
    if not d.is_dir():
        return []
    latest = {}
    for f in d.glob("*.v*.json"):
        m = re.match(r"^(.+)\.v(\d+)\.json$", f.name)
        if not m:
            continue
        draft_id, ver = m.group(1), int(m.group(2))
        if draft_id not in latest or ver > latest[draft_id]:
            latest[draft_id] = ver
    return [
        Draft.model_validate_json((d / f"{did}.v{ver}.json").read_text(encoding="utf-8"))
        for did, ver in sorted(latest.items())
    ]
