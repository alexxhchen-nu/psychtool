"""Regression tests for Task 6 independent-review fixes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from psychtool.core.claims import add_claim
from psychtool.core.draft import (
    BudgetExceeded,
    generate_draft,
    load_draft,
)
from psychtool.core.egress import EgressRunner, EgressStaleError, SourceRef
from psychtool.core.eval import load_fixture, run_case, run_eval
from psychtool.core.judge import judge_draft
from psychtool.core.review import validate_source_refs
from psychtool.core.workspace import init_workspace


class StaticRunner(EgressRunner):
    def __init__(self, output: str = "Generated text.") -> None:
        self.output = output
        self.calls = []

    def run(self, *, workspace, prompt, purpose, source_refs):
        self.calls.append((workspace, prompt, purpose, source_refs))
        return self.output


class MutatingDraftRunner(EgressRunner):
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.prompt = ""

    def run(self, *, workspace, prompt, purpose, source_refs):
        self.prompt = prompt
        _add_claim(self.workspace, "c1", "new claim version")
        return "Draft generated from old claim."


def _add_claim(workspace: Path, claim_id: str, text: str):
    return add_claim(
        workspace,
        claim_id=claim_id,
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="synthetic intake",
        record_time="synthetic date",
        category="client_statement",
        topic="history",
        text=text,
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "case-a", case_id="case-a")
    _add_claim(workspace, "c1", "old claim version")
    return workspace


def _fixture() -> dict:
    path = Path(__file__).parent.parent / "fixtures" / "adolescent-background.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_max_cost_is_rejected_before_strict_runner_call(tmp_path):
    workspace = _workspace(tmp_path)
    runner = StaticRunner()

    with pytest.raises(
        BudgetExceeded,
        match="strict egress runner does not support cost enforcement",
    ):
        generate_draft(
            workspace,
            draft_id="d1",
            claim_ids=["c1"],
            instructions="Write.",
            runner=runner,
            max_cost=1.0,
        )

    assert runner.calls == []
    assert list((workspace / "egress").glob("*.json")) == []
    assert not (workspace / "drafts" / "d1.v1.json").exists()


def test_raw_callback_is_rejected_by_draft_before_it_runs(tmp_path):
    workspace = _workspace(tmp_path)
    calls = []

    with pytest.raises(TypeError, match="EgressRunner"):
        generate_draft(
            workspace,
            draft_id="d1",
            claim_ids=["c1"],
            instructions="Write.",
            runner=lambda **kwargs: calls.append(kwargs),
        )

    assert calls == []
    assert not (workspace / "drafts" / "d1.v1.json").exists()


def test_raw_callback_is_rejected_by_eval_before_workspace_creation(tmp_path):
    root = tmp_path / "eval-root"
    calls = []

    with pytest.raises(TypeError, match="EgressRunner"):
        run_eval(_fixture(), runner=lambda **kwargs: calls.append(kwargs), root=root)

    assert calls == []
    assert not root.exists()


def test_raw_callback_is_rejected_by_run_case_before_workspace_creation(tmp_path):
    fixture = _fixture()
    root = tmp_path / "case-root"

    with pytest.raises(TypeError, match="EgressRunner"):
        run_case(fixture["cases"][0], fixture["cases"], root, lambda **kwargs: None)

    assert not root.exists()


def test_raw_callback_is_rejected_by_judge_before_model_call(tmp_path):
    workspace = _workspace(tmp_path)
    generate_draft(
        workspace,
        draft_id="d1",
        claim_ids=["c1"],
        instructions="Write.",
        runner=StaticRunner(),
    )
    calls = []

    with pytest.raises(TypeError, match="EgressRunner"):
        judge_draft(workspace, "d1", runner=lambda **kwargs: calls.append(kwargs))

    assert calls == []


@pytest.mark.parametrize("data_class", [None, "partly_synthetic", "real"])
def test_run_eval_rejects_non_synthetic_fixture_before_workspace_or_runner(
    tmp_path, data_class
):
    fixture = _fixture()
    if data_class is None:
        fixture.pop("data_class")
    else:
        fixture["data_class"] = data_class
    runner = StaticRunner()
    root = tmp_path / "eval-root"

    with pytest.raises(ValueError, match="data_class must be entirely_synthetic"):
        run_eval(fixture, runner=runner, root=root)

    assert runner.calls == []
    assert not root.exists()


@pytest.mark.parametrize("payload", [{"cases": []}, {"data_class": "real", "cases": []}])
def test_load_fixture_rejects_non_synthetic_data_class(tmp_path, payload):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="data_class must be entirely_synthetic"):
        load_fixture(path)


def test_draft_claim_snapshot_does_not_drift_during_runner_call(tmp_path):
    workspace = _workspace(tmp_path)
    runner = MutatingDraftRunner(workspace)

    draft = generate_draft(
        workspace,
        draft_id="d1",
        claim_ids=["c1"],
        instructions="Write.",
        runner=runner,
    )

    assert "old claim version" in runner.prompt
    assert "new claim version" not in runner.prompt
    assert draft.citations[0].claim_version == 1
    assert draft.citations[0].statement == "old claim version"


def test_judge_uses_frozen_claim_version_and_freshness_detects_stale(tmp_path):
    workspace = _workspace(tmp_path)
    generate_draft(
        workspace,
        draft_id="d1",
        claim_ids=["c1"],
        instructions="Write.",
        runner=StaticRunner("Draft text."),
    )
    _add_claim(workspace, "c1", "new claim version")
    runner = StaticRunner('{"verdict":"supported","explanation":"ok"}')

    judge_draft(workspace, "d1", runner=runner)

    refs = runner.calls[0][3]
    assert SourceRef(kind="claim", id="c1", version=1) in refs
    assert "old claim version" in runner.calls[0][1]
    with pytest.raises(EgressStaleError):
        validate_source_refs(workspace, refs)


def test_old_draft_without_claim_version_does_not_bind_latest(tmp_path):
    workspace = _workspace(tmp_path)
    (workspace / "drafts" / "legacy.v1.json").write_text(
        json.dumps(
            {
                "id": "legacy",
                "case_id": "case-a",
                "version": 1,
                "claim_ids": ["c1"],
                "text": "Legacy text.",
                "citations": [
                    {
                        "claim_id": "c1",
                        "source_document_id": "doc-1",
                        "source_version": 1,
                        "source_passage_id": "p001",
                        "statement": "old claim version",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _add_claim(workspace, "c1", "new claim version")
    draft = load_draft(workspace, "legacy")
    runner = StaticRunner()

    assert draft.citations[0].claim_version is None
    with pytest.raises(ValueError, match="claim_version"):
        judge_draft(workspace, "legacy", runner=runner)
    assert runner.calls == []
