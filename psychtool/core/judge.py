"""LLM judge for per-claim semantic support.

The judge is a *separate* model slot (ADR 0007): its verdicts are archived and
explicitly flagged as not-the-single-source-of-truth (human spot-check required).
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from psychtool.core.claims import get_claim_version
from psychtool.core.draft import load_draft
from psychtool.core.egress import EgressRunner, SourceRef, require_egress_runner

Verdict = Literal["supported", "unsupported", "unclear"]
JUDGE_TEMPLATE = "judge.txt"
JUDGEMENTS_DIR = "judgements"
NOT_SOLE_TRUTH_NOTE = "judge 非唯一真值，需人工抽检"


class JudgeResult(BaseModel):
    claim_id: str
    claim_version: int | None = None
    statement: str
    source_document_id: str
    source_version: int
    source_passage_id: str
    verdict: Verdict
    explanation: str


def _template() -> str:
    return files("psychtool.templates").joinpath(JUDGE_TEMPLATE).read_text(encoding="utf-8")


def build_judge_prompt(statement: str, locator: str, draft_text: str) -> str:
    return _template().format(statement=statement, locator=locator, draft_text=draft_text)


def parse_verdict(output: str) -> tuple[Verdict, str]:
    try:
        data = json.loads(output)
        v = str(data.get("verdict", "")).strip().lower()
        if v in ("supported", "unsupported", "unclear"):
            return v, str(data.get("explanation", ""))
    except Exception:
        pass
    low = output.lower()
    for key in ("unsupported", "unclear", "supported"):
        if key in low:
            return key, output.strip()
    return "unclear", output.strip()


def _latest_version(dirpath: Path, draft_id: str) -> int:
    if not dirpath.is_dir():
        return 0
    versions = []
    for f in dirpath.glob(f"{draft_id}.v*.json"):
        m = re.match(rf"^{re.escape(draft_id)}\.v(\d+)\.json$", f.name)
        if m:
            versions.append(int(m.group(1)))
    return max(versions, default=0)


def judge_draft(
    workspace: Path,
    draft_id: str,
    *,
    runner: EgressRunner,
    context: dict | None = None,
) -> dict:
    runner = require_egress_runner(runner)
    workspace = Path(workspace)
    draft = load_draft(workspace, draft_id)

    results: list[JudgeResult] = []
    for c in draft.citations:
        if c.claim_version is None:
            raise ValueError("draft citation is missing claim_version")
        claim = get_claim_version(workspace, c.claim_id, c.claim_version)
        if claim.text != c.statement:
            raise ValueError("draft citation statement does not match claim_version")
        locator = f"{c.source_document_id} v{c.source_version} 段落 {c.source_passage_id}"
        prompt = build_judge_prompt(c.statement, locator, draft.text)
        source_refs = [
            SourceRef(kind="draft", id=draft.id, version=draft.version),
            SourceRef(kind="claim", id=claim.id, version=claim.version),
        ]
        output = runner.run(
            workspace=workspace,
            prompt=prompt,
            purpose="judge",
            source_refs=source_refs,
        )
        verdict, explanation = parse_verdict(output)
        results.append(
            JudgeResult(
                claim_id=c.claim_id,
                claim_version=c.claim_version,
                statement=c.statement,
                source_document_id=c.source_document_id,
                source_version=c.source_version,
                source_passage_id=c.source_passage_id,
                verdict=verdict,
                explanation=explanation,
            )
        )

    archive = {
        "draft_id": draft_id,
        "case_id": draft.case_id,
        "note": NOT_SOLE_TRUTH_NOTE,
        "context": context or {},
        "results": [r.model_dump() for r in results],
        "support_rate": support_rate(results),
    }

    outdir = workspace / JUDGEMENTS_DIR
    outdir.mkdir(exist_ok=True)
    version = _latest_version(outdir, draft_id) + 1
    (outdir / f"{draft_id}.v{version}.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return archive


def support_rate(results: list[JudgeResult]) -> float:
    if not results:
        return 1.0
    return sum(1 for r in results if r.verdict == "supported") / len(results)
