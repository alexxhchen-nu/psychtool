"""Evaluation harness: frozen fixture, single vs staged generation, hard gates.

Hard gates are pure, deterministic checks (structural, not semantic). The
semantic "does this citation actually support this sentence" question is
deferred to the LLM judge (ticket 09).

Gates (per ticket 08):
1. forbidden   - the draft contains a ``forbidden_claims`` substring (fabricated
                 diagnosis / scores / cause / fabricated date / encoded leakage).
2. leakage     - the draft contains the *other* case's distinctive content
                 (its expected-claim sentences or its case id).
3. conflict    - for each unresolved topic, the draft silently resolves it to a
                 single value (mentions one source's term, drops the other).
4. stale       - after a source revision, a draft still rides a stale citation
                 (reuses the review module's invalidation).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from psychtool.core.workspace import init_workspace, import_material, list_materials
from psychtool.core.claims import add_claim
from psychtool.core.draft import freeze_draft_input, persist_generated_draft
from psychtool.core.egress import (
    EgressRunner,
    SourceRef,
    require_egress_runner,
)
from psychtool.core.review import find_stale_claims, reopen_stale_claims, stale_drafts
from psychtool.core.redact import gate_pii

_INFORMANT_TO_ROLE = {"本人": "self_report", "照护者": "other_report", "教师": "other_report"}
_MONTH_RE = re.compile(r"[零一二三四五六七八九十\d]+月")


def fingerprint(fixture: dict) -> str:
    return hashlib.sha256(
        json.dumps(fixture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def validate_eval_fixture(fixture: dict) -> dict:
    """Accept only fixtures explicitly classified as entirely synthetic."""
    if not isinstance(fixture, dict) or fixture.get("data_class") != "entirely_synthetic":
        raise ValueError("fixture data_class must be entirely_synthetic")
    return fixture


def load_fixture(path: Path | str) -> dict:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_eval_fixture(fixture)


# --- gate primitives -------------------------------------------------------

def gate_forbidden(text: str, forbidden_claims: list[str]) -> list[str]:
    low = text.lower()
    return [f for f in forbidden_claims if f.lower() in low]


def gate_leakage(text: str, other_case: dict) -> list[str]:
    hits: list[str] = []
    low = text.lower()
    if other_case["case_id"].lower() in low:
        hits.append(f"case_id {other_case['case_id']}")
    for fc in other_case.get("expected_claims", []):
        claim = fc["claim"]
        if claim.lower() in low:
            hits.append(claim)
    return hits


def _topic_terms(case: dict, topic: dict) -> set[str]:
    """Distinct month/date terms across a topic's source paragraphs."""
    by_para = {}
    for doc in case["documents"]:
        for p in doc["paragraphs"]:
            by_para[p["id"]] = p["text"]
    terms: set[str] = set()
    for src in topic["sources"]:
        text = by_para.get(src, "")
        terms.update(_MONTH_RE.findall(text))
    return terms


def gate_conflict(text: str, case: dict) -> list[str]:
    flags: list[str] = []
    for topic in case.get("expected_unresolved", []):
        terms = _topic_terms(case, topic)
        if len(terms) < 2:
            continue
        present = [t for t in terms if t in text]
        # silently resolved: exactly one of the conflicting terms survives,
        # and the draft does not mark the discrepancy as unresolved.
        if len(present) == 1 and not any(
            k in text for k in ("未知", "不一致", "不同说法", "存在差异", "待核对")
        ):
            flags.append(f"{topic['topic']}: 仅保留 {present[0]}, 丢弃 {sorted(terms - set(present))}")
    return flags


# --- fixture -> workspace --------------------------------------------------

def _paragraph_to_doc(case: dict) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for doc in case["documents"]:
        for p in doc["paragraphs"]:
            out[p["id"]] = (doc["id"], doc["version"])
    return out


def build_workspace(case: dict, root: Path) -> Path:
    ws = init_workspace(root / case["case_id"], case_id=case["case_id"])
    material_versions: dict[str, int] = {}
    for doc in case["documents"]:
        text = "\n\n".join(p["text"] for p in doc["paragraphs"])
        material = import_material(
            ws,
            material_id=doc["id"],
            title=doc["id"],
            provider=doc["informant"],
            date=doc["recorded_on"],
            text=text,
        )
        material_versions[material.id] = material.version
    p2d = _paragraph_to_doc(case)
    for fc in case.get("expected_claims", []):
        doc_id, _fixture_version = p2d[fc["source"]]
        add_claim(
            ws,
            claim_id=fc["id"],
            source_document_id=doc_id,
            source_version=material_versions[doc_id],
            source_passage_id=fc["source"],
            provider_role=_INFORMANT_TO_ROLE.get(fc["attribution"], "other_report"),
            observation_setting=case["label"],
            record_time="2026-10-12",
            category="client_statement",
            topic=fc.get("topic", "general"),
            text=fc["claim"],
        )
    return ws


# --- orchestration ---------------------------------------------------------

def _extract_prompt(case: dict) -> str:
    lines = ["从以下材料提取事实陈述（保留归属与不确定性）："]
    for doc in case["documents"]:
        lines.append(f"[{doc['id']} v{doc['version']} {doc['informant']}]")
        for p in doc["paragraphs"]:
            lines.append(f"  {p['id']}: {p['text']}")
    return "\n".join(lines)


def run_case(
    case: dict,
    all_cases: dict,
    root: Path,
    runner: EgressRunner,
) -> dict:
    runner = require_egress_runner(runner)
    ws = build_workspace(case, root)
    claim_ids = [fc["id"] for fc in case.get("expected_claims", [])]
    material_refs = [
        SourceRef(kind="material", id=material.id, version=material.version)
        for material in list_materials(ws)
    ]

    other_cases = [c for c in all_cases if c["case_id"] != case["case_id"]]

    # single-step: draft directly from the expected claims
    frozen = freeze_draft_input(
        ws,
        claim_ids=claim_ids,
        instructions="写背景段落",
    )
    single_text = runner.run(
        workspace=ws,
        prompt=frozen.prompt,
        purpose="eval",
        source_refs=list(frozen.source_refs) or material_refs,
    )
    single = persist_generated_draft(
        ws,
        draft_id="single",
        frozen_input=frozen,
        text=single_text,
    )
    # staged: extract-then-generate, with both calls bound to imported materials.
    extracted = runner.run(
        workspace=ws,
        prompt=_extract_prompt(case),
        purpose="eval",
        source_refs=material_refs,
    )
    staged_text = runner.run(
        workspace=ws,
        prompt=f"根据以下提取内容写背景段落：\n{extracted}",
        purpose="eval",
        source_refs=material_refs,
    )

    results = {"case_id": case["case_id"], "single": {}, "staged": {}}
    for label, text in (("single", single.text), ("staged", staged_text)):
        g = results[label]
        g["forbidden"] = gate_forbidden(text, case.get("forbidden_claims", []))
        g["leakage"] = [h for oc in other_cases for h in gate_leakage(text, oc)]
        g["conflict"] = gate_conflict(text, case)
        g["pii"] = gate_pii(text)
        g["blocked"] = bool(g["forbidden"] or g["leakage"] or g["conflict"] or g["pii"])

    # stale gate: verify the system *correctly invalidates* after a source
    # revision (a pass is detection, not a version-block).
    _apply_revision(case, ws)
    stale_ids = [c.id for c in find_stale_claims(ws)]
    affected = stale_drafts(ws)
    reopened = reopen_stale_claims(ws) if stale_ids else 0
    results["stale"] = {
        "revision_applied": case.get("_revision") is not None,
        "stale_claims": stale_ids,
        "stale_drafts": affected,
        "reopened": reopened,
        "detected": bool(stale_ids and affected),
    }
    return results


def _apply_revision(case: dict, ws: Path) -> bool:
    rev = case.get("_revision")
    if rev is None:
        return False
    for doc in case["documents"]:
        if doc["id"] == rev["document_id"]:
            paras = []
            for p in doc["paragraphs"]:
                if p["id"] == rev["paragraph_id"]:
                    paras.append(rev["replacement"])
                else:
                    paras.append(p["text"])
            import_material(
                ws,
                material_id=doc["id"],
                title=doc["id"],
                provider=doc["informant"],
                date=doc["recorded_on"],
                text="\n\n".join(paras),
            )
            return True
    return False


def run_eval(fixture: dict, *, runner: EgressRunner, root: Path) -> dict:
    runner = require_egress_runner(runner)
    fixture = validate_eval_fixture(fixture)
    cases = fixture["cases"]
    revision = fixture.get("source_revision_scenario")
    per_case = {}
    for case in cases:
        # attach the revision scenario to the case it names
        c = dict(case)
        if revision and revision.get("case_id") == case["case_id"]:
            c["_revision"] = revision
        per_case[case["case_id"]] = run_case(
            c,
            cases,
            root / case["case_id"],
            runner,
        )
    return {
        "fingerprint": fingerprint(fixture),
        "cases": per_case,
    }
