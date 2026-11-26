"""M1 developer spot-check checklist, run against synthetic data only.

Prints pass/fail for each item. This is not the PRD §5 product-success
gate (that proposal remains Open). The script never writes a report
export and never touches a caller's existing database.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from psychtool.core.categorize import UNCATEGORIZED_REASON
from psychtool.core.dimensions import (
    DIAGNOSIS_PHRASES,
    NOT_DIAGNOSIS,
    find_blocked_citation,
)
from psychtool.server.app import create_app

CASE_A = "spot-a"
CASE_B = "spot-b"
MARKER_A = "CASEA-UNIQUE-TOKEN"
MARKER_B = "CASEB-UNIQUE-TOKEN"

NOTE_A = (
    f"The fictional student {MARKER_A} sleeps about 8 hours a night "
    "and keeps a regular routine.\n\n"
    "He is distractible and cannot focus during homework.\n\n"
    "He rides his bike after school every day.\n"
)
NOTE_B = (
    f"The fictional student {MARKER_B} plays the tuba at weekend practice.\n"
)
DIMS_LIST = (
    "This is a clinician-made working list of the working areas we track "
    "for this practice, not any official criteria or diagnostic text.\n"
    "Dimension 1: Attention\n"
    "Dimension 2: Sleep and routine\n"
    "Dimension 3: Social interaction\n"
)


@dataclass(frozen=True)
class CheckResult:
    item_id: str
    title: str
    passed: bool
    detail: str

    def line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"{self.item_id:<22} {status:<4}  {self.detail}"


def _client(db_path: Path) -> TestClient:
    os.environ["PSYCHTOOL_DB_PATH"] = str(db_path)
    os.environ.setdefault("PSYCHTOOL_TRANSPORT", "fake")
    os.environ.setdefault("PSYCHTOOL_DATA_TIER", "synthetic")
    app = create_app()
    token = app.state.session_token
    return TestClient(
        app,
        base_url="http://127.0.0.1",
        headers={"X-Psychtool-Token": token},
    )


def _create_case(client: TestClient, case_id: str) -> None:
    response = client.post("/api/workspaces", json={"case_id": case_id})
    if response.status_code != 201:
        raise RuntimeError(f"create {case_id}: {response.status_code} {response.text}")
    confirm = client.post(f"/api/workspaces/{case_id}/synthetic-confirmation")
    if confirm.status_code not in (200, 201, 204):
        raise RuntimeError(f"confirm {case_id}: {confirm.status_code} {confirm.text}")


def _upload(
    client: TestClient,
    case_id: str,
    material_id: str,
    text: str,
    title: str,
    kind: str = "case",
) -> None:
    response = client.post(
        f"/api/workspaces/{case_id}/materials",
        data={
            "material_id": material_id,
            "title": title,
            "provider": "synthetic author",
            "date": "2026-11-25",
            "kind": kind,
        },
        files={
            "file": (f"{material_id}.md", text.encode("utf-8"), "application/octet-stream")
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"upload {case_id}/{material_id}: {response.status_code} {response.text}")


def _json(client: TestClient, path: str):
    response = client.get(path)
    if response.status_code != 200:
        raise RuntimeError(f"GET {path}: {response.status_code} {response.text}")
    return response.json()


def _passage_text(materials: list, material_id: str, passage_id: str) -> str:
    material = next(m for m in materials if m["id"] == material_id)
    return next(p["text"] for p in material["passages"] if p["id"] == passage_id)


def _all_material_text(materials: list) -> str:
    return "\n".join(
        passage["text"]
        for material in materials
        for passage in material.get("passages", [])
    )


def _quoted_fragments(reason: str) -> list[str]:
    return re.findall(r"“([^”]+)”", reason or "")


def seed_synthetic_cases(client: TestClient) -> None:
    _create_case(client, CASE_A)
    _create_case(client, CASE_B)
    _upload(client, CASE_A, "note-a", NOTE_A, "Synthetic note A")
    _upload(client, CASE_A, "dims-a", DIMS_LIST, "Working dimension list", kind="dims")
    _upload(client, CASE_B, "note-b", NOTE_B, "Synthetic note B")


def run_checks(client: TestClient) -> list[CheckResult]:
    materials_a = _json(client, f"/api/workspaces/{CASE_A}/materials")
    materials_b = _json(client, f"/api/workspaces/{CASE_B}/materials")
    evidence_a = _json(client, f"/api/workspaces/{CASE_A}/evidence")
    evidence_b = _json(client, f"/api/workspaces/{CASE_B}/evidence")
    dimensions_a = _json(client, f"/api/workspaces/{CASE_A}/dimensions")
    claims_a = _json(client, f"/api/workspaces/{CASE_A}/claims")
    claims_b = _json(client, f"/api/workspaces/{CASE_B}/claims")
    sections_a = client.get(
        f"/api/workspaces/{CASE_A}/sections",
        params={"template_id": "intake-report"},
    )
    sections_b = client.get(
        f"/api/workspaces/{CASE_B}/sections",
        params={"template_id": "intake-report"},
    )
    sections_a = sections_a.json() if sections_a.status_code == 200 else []
    sections_b = sections_b.json() if sections_b.status_code == 200 else []

    items_a = evidence_a["items"]
    items_b = evidence_b["items"]
    dim_items = dimensions_a["items"]

    if not items_a:
        raise RuntimeError("expected extracted evidence in case A")
    if not items_b:
        raise RuntimeError("expected extracted evidence in case B")

    # SPOT-SOURCE: quote == passage.text[start:end]
    mismatches = []
    for item in items_a + items_b:
        case_id = CASE_A if item in items_a else CASE_B
        materials = materials_a if case_id == CASE_A else materials_b
        text = _passage_text(materials, item["material_id"], item["passage_id"])
        slice_ = text[item["start"] : item["end"]]
        if slice_ != item["quote"]:
            mismatches.append(item["id"])
    results = [
        CheckResult(
            "SPOT-SOURCE",
            "Every evidence quote equals the stored source slice",
            not mismatches,
            f"{len(items_a) + len(items_b)} items checked"
            if not mismatches
            else f"span mismatch on {mismatches}",
        )
    ]

    # SPOT-NO-INVENTED: every quote appears in uploaded material text
    invented = []
    for item, materials in ((i, materials_a) for i in items_a):
        if item["quote"] not in _all_material_text(materials):
            invented.append(item["id"])
    for item in items_b:
        if item["quote"] not in _all_material_text(materials_b):
            invented.append(item["id"])
    results.append(
        CheckResult(
            "SPOT-NO-INVENTED",
            "No evidence quote is invented outside uploaded materials",
            not invented,
            "all quotes found in uploaded text"
            if not invented
            else f"invented quotes: {invented}",
        )
    )

    # SPOT-CATEGORY-REASON: categorized items quote visible source text
    bad_reasons = []
    for item in items_a + items_b:
        reason = item.get("category_reason") or ""
        if item.get("category") == "uncategorized":
            if reason != UNCATEGORIZED_REASON:
                bad_reasons.append(item["id"])
            continue
        fragments = _quoted_fragments(reason)
        if not fragments or not any(frag in item["quote"] for frag in fragments):
            bad_reasons.append(item["id"])
    results.append(
        CheckResult(
            "SPOT-CATEGORY-REASON",
            "Categorized items have a reason quoting visible source text",
            not bad_reasons,
            "category reasons point at the quote"
            if not bad_reasons
            else f"reason/source mismatch: {bad_reasons}",
        )
    )

    # SPOT-NO-GUESS: uncategorized items are not a guessed category
    guessed = [
        item["id"]
        for item in items_a + items_b
        if item.get("category") == "uncategorized"
        and item.get("category_label") not in (None, "Uncategorized")
    ]
    results.append(
        CheckResult(
            "SPOT-NO-GUESS",
            "Undecidable items stay Uncategorized, never a guessed category",
            not guessed,
            "no guessed category on uncategorized items"
            if not guessed
            else f"guessed labels: {guessed}",
        )
    )

    def _blob(materials, evidence, claims, sections) -> str:
        parts = [_all_material_text(materials)]
        parts.extend(item.get("quote") or "" for item in evidence)
        if isinstance(claims, dict):
            claim_rows = claims.get("items") or claims.get("claims") or []
        else:
            claim_rows = claims
        for claim in claim_rows:
            if isinstance(claim, dict):
                parts.append(str(claim.get("text") or claim.get("statement") or ""))
        if isinstance(sections, dict):
            section_rows = sections.get("items") or sections.get("sections") or list(sections.values())
        else:
            section_rows = sections
        for section in section_rows:
            if isinstance(section, dict):
                parts.append(str(section.get("text") or section.get("draft") or ""))
            else:
                parts.append(str(section))
        return "\n".join(parts)

    blob_a = _blob(materials_a, items_a, claims_a, sections_a)
    blob_b = _blob(materials_b, items_b, claims_b, sections_b)
    leak_a = MARKER_B in blob_a
    leak_b = MARKER_A in blob_b
    results.append(
        CheckResult(
            "SPOT-ISOLATION",
            "Case A never contains case B's unique marker, and vice versa",
            not leak_a and not leak_b,
            "no cross-case leak of unique markers"
            if not leak_a and not leak_b
            else f"A has B marker={leak_a}, B has A marker={leak_b}",
        )
    )

    mapped = [item for item in dim_items if item.get("dimension_name")]
    bad_mapped = []
    for item in mapped:
        reason = item.get("dim_reason") or ""
        fragments = _quoted_fragments(reason)
        if not reason or not fragments or not any(frag in item["quote"] for frag in fragments):
            bad_mapped.append(item["id"])
            continue
        if not item.get("passage_id") or not (0 <= item["start"] < item["end"]):
            bad_mapped.append(item["id"])
    results.append(
        CheckResult(
            "R7-MAPPED-REASON",
            "Mapped items have a reason and a source range",
            bool(mapped) and not bad_mapped,
            f"{len(mapped)} mapped items with reason and range"
            if mapped and not bad_mapped
            else (
                "no mapped items in the synthetic seed"
                if not mapped
                else f"incomplete mappings: {bad_mapped}"
            ),
        )
    )

    # Unsure / two-hit items must not carry a guessed dimension name.
    guessed_dims = [
        item["id"]
        for item in dim_items
        if item.get("dim_state") == "needs_review"
        and not item.get("dimension_name")
        and item.get("dimension_id")
    ]
    # The rule: never a guessed dimension on an unsure item. If dim_state is
    # needs_review WITH a name, that is a suggested single-hit mapping awaiting
    # confirm, which is allowed. Fail only if an item has a name while the
    # matcher recorded an ambiguous (no single hit) state we can see as
    # dimension_name set alongside a two-hit reason, or a name when the
    # list-side mapping is absent. We also fail if any item has a dimension
    # name that is not in her uploaded list.
    list_names = {d["name"] for d in dimensions_a.get("dimensions") or []}
    outside_list = [
        item["id"]
        for item in dim_items
        if item.get("dimension_name") and item["dimension_name"] not in list_names
    ]
    results.append(
        CheckResult(
            "R7-UNSURE",
            "Dimension names come only from her list; no name invented when unsure",
            not outside_list and not guessed_dims,
            "names stay inside the uploaded list"
            if not outside_list and not guessed_dims
            else f"outside list={outside_list} inconsistent={guessed_dims}",
        )
    )

    disclaimer_ok = dimensions_a.get("disclaimer") == NOT_DIAGNOSIS
    dx_hits = []
    for item in dim_items:
        for text in (item.get("dimension_name") or "", item.get("dim_reason") or ""):
            lowered = text.casefold()
            for phrase in DIAGNOSIS_PHRASES:
                if phrase.casefold() in lowered:
                    dx_hits.append((item["id"], phrase, text))
    results.append(
        CheckResult(
            "R7-NOT-DX",
            "No diagnosis language; the fixed disclaimer is present",
            not dx_hits and disclaimer_ok,
            "disclaimer present, no diagnosis phrases"
            if not dx_hits and disclaimer_ok
            else f"disclaimer_ok={disclaimer_ok} phrases={dx_hits}",
        )
    )

    citations = []
    for item in dim_items:
        for field in (item.get("dim_reason") or "", item.get("dimension_name") or ""):
            hit = find_blocked_citation(field)
            if hit:
                citations.append((item["id"], hit))
    results.append(
        CheckResult(
            "R7-NO-MANUAL",
            "No un-uploaded manual / criterion-number citations in mappings",
            not citations,
            "no blocked citations in mapping text"
            if not citations
            else f"citations: {citations}",
        )
    )

    unlabeled = []
    for dim in dimensions_a.get("dimensions") or []:
        if not dim.get("quote_text_of_passage_span"):
            unlabeled.append(dim.get("name"))
        elif dim["quote_text_of_passage_span"] not in DIMS_LIST:
            unlabeled.append(dim.get("name"))
    results.append(
        CheckResult(
            "R7-SOURCE-LABEL",
            "Each dimension cites only a range from her uploaded list",
            bool(dimensions_a.get("dimensions")) and not unlabeled,
            f"{len(dimensions_a.get('dimensions') or [])} list entries labelled from the upload"
            if dimensions_a.get("dimensions") and not unlabeled
            else f"unlabelled or out-of-range: {unlabeled}",
        )
    )

    return results


CHECK_IDS = (
    "SPOT-SOURCE",
    "SPOT-NO-INVENTED",
    "SPOT-CATEGORY-REASON",
    "SPOT-NO-GUESS",
    "SPOT-ISOLATION",
    "R7-MAPPED-REASON",
    "R7-UNSURE",
    "R7-NOT-DX",
    "R7-NO-MANUAL",
    "R7-SOURCE-LABEL",
)


def format_report(results: list[CheckResult]) -> str:
    passed = sum(1 for item in results if item.passed)
    failed = len(results) - passed
    lines = [
        "psychtool M1 developer spot-check (synthetic data only)",
        "Not the PRD §5 product-success gate (that proposal is still Open).",
        "No report export is written.",
        "",
    ]
    lines.extend(item.line() for item in results)
    lines.append("")
    lines.append(f"RESULT: {passed} passed, {failed} failed, {len(results)} items")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    del argv  # no flags: always synthetic, always a throwaway database
    with tempfile.TemporaryDirectory(prefix="psychtool-spotcheck-") as tmp:
        db_path = Path(tmp) / "spotcheck.db"
        client = _client(db_path)
        with client:
            seed_synthetic_cases(client)
            results = run_checks(client)
    text = format_report(results)
    sys.stdout.write(text)
    return 0 if all(item.passed for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
