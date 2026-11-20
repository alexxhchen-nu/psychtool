"""Export a draft and its source index to a user-specified location.

Export is user-triggered; it writes the already-generated draft verbatim plus a
source index (no model call, no re-interpretation). It records the export in the
workspace ``exports.log`` (no sensitive original text beyond the draft).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from psychtool.core.draft import load_draft, Draft

EXPORT_LOG = "exports.log"


def preview_export(workspace: Path, draft_id: str) -> dict:
    draft = load_draft(workspace, draft_id)
    return {
        "draft_id": draft.id,
        "version": draft.version,
        "case_id": draft.case_id,
        "text": draft.text,
        "sources": [
            {
                "claim_id": c.claim_id,
                "source_document_id": c.source_document_id,
                "source_version": c.source_version,
                "source_passage_id": c.source_passage_id,
                "statement": c.statement,
            }
            for c in draft.citations
        ],
    }


def _render(draft: Draft) -> str:
    lines = [draft.text, "", "## 来源索引", ""]
    for c in draft.citations:
        lines.append(
            f"- [{c.claim_id}] {c.source_document_id} v{c.source_version} "
            f"段落 {c.source_passage_id}：{c.statement}"
        )
    return "\n".join(lines)


def _log_export(workspace: Path, draft_id: str, target: Path) -> None:
    entry = {
        "draft_id": draft_id,
        "target": str(target),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with (workspace / EXPORT_LOG).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def export_draft(workspace: Path, draft_id: str, target_path: Path | str) -> Path:
    workspace = Path(workspace)
    draft = load_draft(workspace, draft_id)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render(draft), encoding="utf-8")
    _log_export(workspace, draft_id, target)
    return target
