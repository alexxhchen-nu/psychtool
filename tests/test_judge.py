"""LLM judge: prompt assembly, verdict parsing, archiving, support rate."""

import json

import pytest

from psychtool.config import Config
from psychtool.core.egress import EgressRequest, EgressRunner, EgressStaleError, SourceRef
from psychtool.core.workspace import import_material, init_workspace
from psychtool.gateway.orchestrator import EgressOrchestrator, SyntheticApproval
from psychtool.core.claims import add_claim
from psychtool.core.draft import freeze_draft_input, persist_generated_draft
from psychtool.core.judge import (
    build_judge_prompt,
    parse_verdict,
    judge_draft,
    support_rate,
    JudgeResult,
    NOT_SOLE_TRUTH_NOTE,
)


class RecordingRunner(EgressRunner):
    def __init__(self):
        self.calls = []

    def run(self, *, workspace, prompt, purpose, source_refs):
        self.calls.append((workspace, prompt, purpose, source_refs))
        return '{"verdict":"supported","explanation":"ok"}'


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
        text="草稿正文。",
    )
    return ws


def test_build_judge_prompt_contains_statement_and_locator():
    p = build_judge_prompt("本人报告入睡困难。", "doc-1 v1 段落 p001", "草稿正文。")
    assert "本人报告入睡困难。" in p
    assert "doc-1 v1 段落 p001" in p
    assert "supported" in p


def test_parse_verdict_json():
    assert parse_verdict('{"verdict":"supported","explanation":"忠实"}') == ("supported", "忠实")


def test_parse_verdict_fallback_keyword():
    assert parse_verdict("The claim is unsupported here.") == ("unsupported", "The claim is unsupported here.")


def test_parse_verdict_unknown_defaults_unclear():
    assert parse_verdict("whatever") == ("unclear", "whatever")


def test_judge_draft_archives_and_scores(ws):
    _seed(ws)
    runner = RecordingRunner()

    archive = judge_draft(
        ws,
        "d1",
        runner=runner,
        context={"fixture_fingerprint": "abc123"},
    )
    assert archive["draft_id"] == "d1"
    assert archive["note"] == NOT_SOLE_TRUTH_NOTE
    assert archive["context"]["fixture_fingerprint"] == "abc123"
    assert archive["support_rate"] == 1.0
    assert len(archive["results"]) == 1
    assert archive["results"][0]["claim_id"] == "c1"
    assert (ws / "judgements" / "d1.v1.json").is_file()
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == ws
    assert runner.calls[0][2] == "judge"
    assert runner.calls[0][3] == [
        SourceRef(kind="draft", id="d1", version=1),
        SourceRef(kind="claim", id="c1", version=1),
    ]


def test_judge_rejects_reimported_claim_material_before_transport(ws):
    material_fields = dict(
        material_id="doc-1", title="Synthetic source", provider="synthetic",
        date="synthetic date", text="Synthetic observation.",
    )
    import_material(ws, **material_fields)
    _seed(ws)
    assert import_material(ws, **material_fields).version == 2
    calls = []
    runner = EgressOrchestrator(
        config=Config(base_url="https://provider.invalid/v1", model="m1"),
        approval=SyntheticApproval(reason="synthetic fixture"),
        transport=lambda config, envelope: calls.append(envelope) or '{"verdict":"supported"}',
    )

    with pytest.raises(EgressStaleError, match="^egress source reference is stale$"):
        judge_draft(ws, "d1", runner=runner)

    assert calls == []
    assert not (ws / "judgements").exists()
    records = list((ws / "egress").glob("*.json"))
    assert len(records) == 1
    record = EgressRequest.model_validate_json(records[0].read_text(encoding="utf-8"))
    assert record.purpose == "judge"
    assert record.status == "invalidated"
    assert {ref.kind for ref in record.source_refs} == {"draft", "claim"}


def test_support_rate_mixed():
    rs = [
        JudgeResult(claim_id="a", statement="s", source_document_id="d", source_version=1, source_passage_id="p", verdict="supported", explanation=""),
        JudgeResult(claim_id="b", statement="s", source_document_id="d", source_version=1, source_passage_id="p", verdict="unsupported", explanation=""),
    ]
    assert support_rate(rs) == 0.5


def test_support_rate_empty_is_one():
    assert support_rate([]) == 1.0
