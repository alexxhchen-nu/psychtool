"""Candidate claims: provenance, attribution, and verification status.

Each claim carries its source locator (document + version + passage), provider
role, observation setting, record time, event time (may be unknown), category,
topic and original text. Attribution is preserved, never flattened into an
unconditional "objective fact". Verification status changes are versioned.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProviderRole = Literal["self_report", "other_report", "clinician_interpretation"]
VerificationStatus = Literal["pending", "verified", "conflict-viewed"]

CLAIMS_DIR = "claims"


class Claim(BaseModel):
    id: str
    case_id: str
    version: int = 1
    source_document_id: str
    source_version: int
    source_passage_id: str
    provider_role: ProviderRole
    observation_setting: str
    record_time: str
    event_time: str | None = None
    category: str
    topic: str
    text: str
    verification_status: VerificationStatus = "pending"

    @field_validator("provider_role")
    @classmethod
    def _role_known(cls, v: str) -> str:
        allowed = {"self_report", "other_report", "clinician_interpretation"}
        if v not in allowed:
            raise ValueError(f"unknown provider_role: {v!r}")
        return v

    @field_validator("text", "topic", "observation_setting")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be empty")
        return v.strip()


def _latest_version(dirpath: Path, claim_id: str) -> int:
    if not dirpath.is_dir():
        return 0
    versions = []
    for f in dirpath.glob(f"{claim_id}.v*.json"):
        m = re.match(rf"^{re.escape(claim_id)}\.v(\d+)\.json$", f.name)
        if m:
            versions.append(int(m.group(1)))
    return max(versions, default=0)


def _meta(workspace: Path) -> dict:
    return json.loads((workspace / "meta.json").read_text(encoding="utf-8"))


def _claims_dir(workspace: Path) -> Path:
    return workspace / CLAIMS_DIR


def add_claim(workspace: Path, *, claim_id: str, **fields) -> Claim:
    workspace = Path(workspace)
    case_id = _meta(workspace)["case_id"]
    version = _latest_version(_claims_dir(workspace), claim_id) + 1
    claim = Claim(id=claim_id, case_id=case_id, version=version, **fields)
    out = _claims_dir(workspace) / f"{claim_id}.v{version}.json"
    out.write_text(claim.model_dump_json(indent=2), encoding="utf-8")
    return claim


def get_claim_version(workspace: Path, claim_id: str, version: int) -> Claim:
    """Load one exact immutable claim version rather than rebinding to latest."""
    path = _claims_dir(Path(workspace)) / f"{claim_id}.v{version}.json"
    if version < 1 or not path.is_file():
        raise KeyError(f"no claim with id {claim_id!r} at version {version}")
    return Claim.model_validate_json(path.read_text(encoding="utf-8"))


def get_claim(workspace: Path, claim_id: str) -> Claim:
    version = _latest_version(_claims_dir(workspace), claim_id)
    if version == 0:
        raise KeyError(f"no claim with id {claim_id!r}")
    return get_claim_version(workspace, claim_id, version)


def list_claims(workspace: Path) -> list[Claim]:
    d = _claims_dir(workspace)
    if not d.is_dir():
        return []
    latest = {}
    for f in d.glob("*.v*.json"):
        m = re.match(r"^(.+)\.v(\d+)\.json$", f.name)
        if not m:
            continue
        claim_id, ver = m.group(1), int(m.group(2))
        if claim_id not in latest or ver > latest[claim_id]:
            latest[claim_id] = ver
    return [
        Claim.model_validate_json((d / f"{cid}.v{ver}.json").read_text(encoding="utf-8"))
        for cid, ver in sorted(latest.items())
    ]


def mark_status(workspace: Path, claim_id: str, status: VerificationStatus) -> Claim:
    current = get_claim(workspace, claim_id)
    data = current.model_dump()
    data["verification_status"] = status
    version = _latest_version(_claims_dir(workspace), claim_id) + 1
    data["version"] = version
    updated = Claim(**data)
    out = _claims_dir(workspace) / f"{claim_id}.v{version}.json"
    out.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    return updated


def claims_by_topic(workspace: Path, topic: str) -> list[Claim]:
    return [c for c in list_claims(workspace) if c.topic == topic]
