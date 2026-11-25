"""Per-section report state, tied to a report template and its approved claims.

A report is assembled section by section. Each section draft records the text,
the claims it draws on, its review gate (inherited from the template), and a
human-review status. Sections are versioned like materials, claims and drafts,
and are stored under ``sections/<template_id>/<section_id>.vN.json`` inside a
workspace so a case can hold multiple report templates without collision.

Safety invariants enforced here (not in the template file):
- a section cannot reach ``approved`` while its text is empty;
- a ``licensed_clinician`` section requires a non-empty reviewer to approve;
- every cited claim must already exist in the workspace;
- the template and section must match the loaded manifest (id + version).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Union

from pydantic import BaseModel

from psychtool.core.claims import list_claims
from psychtool.core.draft import build_prompt, select_claims
from psychtool.core.egress import SourceRef
from psychtool.core.report_templates import (
    ReportTemplate,
    TemplateSection,
    is_clinician_authored_section,
    load_template,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from psychtool.store.sqlite_store import CaseStore

SectionStatus = Literal["empty", "draft", "needs_review", "approved"]
ReviewGate = Literal["standard", "licensed_clinician"]

SECTIONS_DIR = "sections"

# A JSON workspace directory, or one case bound inside the SQLite store.
SectionTarget = Union[Path, str, "CaseStore"]


class ClinicianAuthoredSectionError(ValueError):
    """Raised when egress is requested for a section the clinician writes.

    The API turns this into a fixed 400 body; no section text, claim ids or
    this message is ever returned to the client or logged.
    """

    def __init__(self, section_id: str) -> None:
        self.section_id = section_id
        super().__init__("clinician-authored sections are not sent to the model")


class SectionDraft(BaseModel):
    section_id: str
    template_id: str
    template_version: int
    case_id: str
    version: int = 1
    text: str
    claim_ids: list[str]
    status: SectionStatus = "draft"
    review_gate: ReviewGate = "standard"
    reviewer: str | None = None
    updated_at: str


def _meta(workspace: Path) -> dict:
    return json.loads((workspace / "meta.json").read_text(encoding="utf-8"))


def _section_dir(workspace: Path, template_id: str) -> Path:
    return Path(workspace) / SECTIONS_DIR / template_id


def _latest_version(dirpath: Path, section_id: str) -> int:
    if not dirpath.is_dir():
        return 0
    versions = []
    for f in dirpath.glob(f"{section_id}.v*.json"):
        m = re.match(rf"^{re.escape(section_id)}\.v(\d+)\.json$", f.name)
        if m:
            versions.append(int(m.group(1)))
    return max(versions, default=0)


def _template_section(template: ReportTemplate, section_id: str) -> TemplateSection:
    for section in template.sections:
        if section.id == section_id:
            return section
    raise KeyError(f"section {section_id!r} not in template {template.template_id!r}")


def _template_gate(template: ReportTemplate, section_id: str) -> ReviewGate:
    return _template_section(template, section_id).review_gate


def _is_case_store(target: object) -> bool:
    return not isinstance(target, (str, Path))


def _case_id(target: SectionTarget) -> str:
    if _is_case_store(target):
        return target.case_id
    return _meta(Path(target))["case_id"]


def _claim_ids(target: SectionTarget) -> set[str]:
    if _is_case_store(target):
        return {c.id for c in target.list_claims()}
    return {c.id for c in list_claims(Path(target))}


def save_section(
    target: SectionTarget,
    *,
    template_id: str,
    template_version: int,
    section_id: str,
    text: str,
    claim_ids: list[str],
    status: SectionStatus = "draft",
    reviewer: str | None = None,
) -> SectionDraft:
    template = load_template(template_id)
    if template.version != template_version:
        raise ValueError(
            f"template {template_id} is at version {template.version}, not {template_version}"
        )
    review_gate = _template_gate(template, section_id)

    available = _claim_ids(target)
    missing = [cid for cid in claim_ids if cid not in available]
    if missing:
        raise KeyError(f"claims not in workspace: {missing}")

    if status == "approved" and not text.strip():
        raise ValueError("cannot approve a section with empty text")
    if status == "approved" and review_gate == "licensed_clinician" and not (reviewer or "").strip():
        raise ValueError("licensed_clinician sections require a reviewer to approve")

    if _is_case_store(target):
        return target.save_section(
            template_id=template_id,
            template_version=template_version,
            section_id=section_id,
            text=text,
            claim_ids=list(dict.fromkeys(claim_ids)),
            status=status,
            review_gate=review_gate,
            reviewer=(reviewer or "").strip() or None,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    workspace = Path(target)
    dirpath = _section_dir(workspace, template_id)
    dirpath.mkdir(parents=True, exist_ok=True)
    version = _latest_version(dirpath, section_id) + 1
    draft = SectionDraft(
        section_id=section_id,
        template_id=template_id,
        template_version=template_version,
        case_id=_meta(workspace)["case_id"],
        version=version,
        text=text,
        claim_ids=list(dict.fromkeys(claim_ids)),
        status=status,
        review_gate=review_gate,
        reviewer=(reviewer or "").strip() or None,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    out = dirpath / f"{section_id}.v{version}.json"
    out.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    return draft


def get_section(target: SectionTarget, template_id: str, section_id: str) -> SectionDraft | None:
    if _is_case_store(target):
        return target.get_section(template_id, section_id)
    workspace = Path(target)
    dirpath = _section_dir(workspace, template_id)
    version = _latest_version(dirpath, section_id)
    if version == 0:
        return None
    raw = (dirpath / f"{section_id}.v{version}.json").read_text(encoding="utf-8")
    return SectionDraft.model_validate_json(raw)


def section_states(target: SectionTarget, template_id: str) -> list[dict]:
    """Ordered state for every section in a template, defaulting to ``empty``."""
    template = load_template(template_id)
    states: list[dict] = []
    for section in template.sections:
        draft = get_section(target, template_id, section.id)
        if draft is None:
            states.append(
                {
                    "section_id": section.id,
                    "title": section.title,
                    "status": "empty",
                    "review_gate": section.review_gate,
                    "required": section.required,
                    "text": "",
                    "claim_ids": [],
                    "version": 0,
                }
            )
        else:
            states.append(
                {
                    "section_id": section.id,
                    "title": section.title,
                    "status": draft.status,
                    "review_gate": draft.review_gate,
                    "required": section.required,
                    "text": draft.text,
                    "claim_ids": draft.claim_ids,
                    "version": draft.version,
                    "reviewer": draft.reviewer,
                }
            )
    return states


def build_section_request_input(
    target: SectionTarget,
    *,
    template_id: str,
    template_version: int,
    section_id: str,
    claim_ids: list[str],
    instructions: str,
) -> tuple[str, list[SourceRef]]:
    """Build a section's complete unredacted prompt and selected sources."""
    template = load_template(template_id)
    if template.version != template_version:
        raise ValueError(
            f"template {template_id} is at version {template.version}, not {template_version}"
        )
    section = _template_section(template, section_id)
    if is_clinician_authored_section(section):
        # Fail closed before selecting claims or building any prompt: these
        # sections may be blank or carry only her selected evidence prompts,
        # never a model-generated conclusion (R9-AC3).
        raise ClinicianAuthoredSectionError(section_id)
    claims = select_claims(target, claim_ids)
    prompt = build_prompt(claims, instructions=instructions)
    source_refs = [
        SourceRef(
            kind="claim",
            id=claim.id,
            version=claim.version,
            evidence_ids=list(claim.evidence_ids),
        )
        for claim in claims
    ]
    return prompt, source_refs
