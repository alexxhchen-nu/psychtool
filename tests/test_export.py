"""Export draft + source index."""

import json

import pytest

from psychtool.core.workspace import init_workspace
from psychtool.core.claims import add_claim
from psychtool.core.draft import freeze_draft_input, persist_generated_draft
from psychtool.core.export import preview_export, export_draft


@pytest.fixture
def ws(tmp_path):
    return init_workspace(tmp_path / "case-a", case_id="case-a")


def _seed(ws):
    add_claim(
        ws, claim_id="c1", source_document_id="doc-1", source_version=1,
        source_passage_id="p001", provider_role="self_report",
        observation_setting="intake", record_time="2026-10-01",
        category="client_statement", topic="t", text="本人报告入睡困难。",
    )
    frozen = freeze_draft_input(ws, claim_ids=["c1"], instructions="x")
    persist_generated_draft(
        ws,
        draft_id="d1",
        frozen_input=frozen,
        text="背景草稿文本。",
    )
    return ws


def test_preview_returns_text_and_sources_without_writing(ws):
    _seed(ws)
    p = preview_export(ws, "d1")
    assert p["text"] == "背景草稿文本。"
    assert len(p["sources"]) == 1
    assert p["sources"][0]["claim_id"] == "c1"
    assert p["sources"][0]["source_passage_id"] == "p001"
    # no target file created by preview
    assert not list((ws / "drafts").parent.glob("export*"))


def test_export_writes_draft_and_source_index(ws):
    _seed(ws)
    target = ws / "out" / "report.md"
    result = export_draft(ws, "d1", target)
    assert result == target
    content = target.read_text(encoding="utf-8")
    assert "背景草稿文本。" in content
    assert "来源索引" in content
    assert "doc-1 v1 段落 p001" in content
    assert "本人报告入睡困难。" in content


def test_export_logs_entry(ws):
    _seed(ws)
    target = ws / "out" / "report.md"
    export_draft(ws, "d1", target)
    log = (ws / "exports.log").read_text(encoding="utf-8")
    entry = json.loads(log.strip().splitlines()[-1])
    assert entry["draft_id"] == "d1"
    assert entry["target"] == str(target)


def test_export_nonexistent_draft_raises(ws):
    with pytest.raises(KeyError):
        export_draft(ws, "nope", ws / "x.md")
