"""Evaluation harness: hard gates + single vs staged, on the frozen fixture."""

import json
from pathlib import Path

import pytest

from psychtool.config import Config
from psychtool.core.egress import EgressApprovalError, EgressRequest, EgressRunner
from psychtool.core.eval import (
    fingerprint,
    load_fixture,
    gate_forbidden,
    gate_leakage,
    gate_conflict,
    run_eval,
)
from psychtool.gateway.orchestrator import EgressOrchestrator, SyntheticApproval

FIXTURE = Path(__file__).parent.parent / "fixtures" / "adolescent-background.json"
_ENV_VARS = (
    "PSYCHTOOL_BASE_URL",
    "PSYCHTOOL_MODEL",
    "PSYCHTOOL_JUDGE_MODEL",
    "PSYCHTOOL_DATA_TIER",
    "PSYCHTOOL_API_KEY",
    "PSYCHTOOL_REDACT",
)


@pytest.fixture(autouse=True)
def _clear_psychtool_environment(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class RecordingRunner(EgressRunner):
    def __init__(self, output):
        self.output = output
        self.calls = []

    def run(self, *, workspace, prompt, purpose, source_refs):
        self.calls.append((workspace, prompt, purpose, source_refs))
        return self.output


def _fixture() -> dict:
    return load_fixture(FIXTURE)


def test_fingerprint_stable():
    fx = _fixture()
    assert fingerprint(fx) == fingerprint(json.loads(json.dumps(fx)))
    assert len(fingerprint(fx)) == 16


def test_gate_forbidden():
    assert gate_forbidden("学生确诊 ADHD。", ["确诊 ADHD"]) == ["确诊 ADHD"]
    assert gate_forbidden("背景正常。", ["确诊 ADHD"]) == []


def test_gate_leakage():
    other = {
        "case_id": "TRAIN-B",
        "expected_claims": [{"id": "B-F1", "source": "B-Y1", "attribution": "本人",
                             "claim": "先安排游泳队训练再写作业。"}],
    }
    assert gate_leakage("该学生先安排游泳队训练再写作业。", other) == ["先安排游泳队训练再写作业。"]
    assert gate_leakage("TRAIN-B 的资料混入。", {"case_id": "TRAIN-B", "expected_claims": []}) == [
        "case_id TRAIN-B"
    ]


def test_gate_conflict_flags_single_resolution():
    case = _fixture()["cases"][0]  # TRAIN-A
    assert gate_conflict("变化开始时间为七月。", case) != []
    assert gate_conflict("本人称九月，照护者称七月，两者不一致。", case) == []


def test_run_eval_clean(tmp_path):
    fx = _fixture()
    runner = RecordingRunner("背景段落（合成，无诊断）。")

    report = run_eval(fx, runner=runner, root=tmp_path)
    assert len(report["fingerprint"]) == 16
    a = report["cases"]["TRAIN-A"]
    assert a["single"]["blocked"] is False
    assert a["staged"]["blocked"] is False
    # source revision correctly detected for TRAIN-A
    assert a["stale"]["revision_applied"] is True
    assert a["stale"]["detected"] is True
    assert len(runner.calls) == len(fx["cases"]) * 3
    assert all(call[2] == "eval" for call in runner.calls)
    assert all(call[3] for call in runner.calls)
    assert {ref.kind for call in runner.calls for ref in call[3]} == {"claim", "material"}


def test_run_eval_forbidden_blocks(tmp_path):
    fx = _fixture()

    runner = RecordingRunner("学生确诊 ADHD。")

    report = run_eval(fx, runner=runner, root=tmp_path)
    a = report["cases"]["TRAIN-A"]
    assert a["single"]["blocked"] is True
    assert "确诊 ADHD" in a["single"]["forbidden"]


def test_eval_transport_only_sees_synthetic_auto_approved_requests(tmp_path):
    fx = _fixture()
    observed = []

    def transport(config, envelope):
        requests = [
            EgressRequest.model_validate_json(path.read_text(encoding="utf-8"))
            for path in tmp_path.rglob("egress/*.json")
        ]
        approved = [request for request in requests if request.status == "approved"]
        assert len(approved) == 1
        request = approved[0]
        observed.append(request)
        assert request.approval_mode == "synthetic_auto"
        assert request.purpose == "eval"
        assert request.source_refs
        return "Synthetic evaluation output."

    runner = EgressOrchestrator(
        config=Config(
            base_url="http://127.0.0.1:11434/v1",
            model="eval-model",
            data_tier="synthetic",
        ),
        approval=SyntheticApproval(reason="frozen fixture"),
        transport=transport,
    )
    run_eval(fx, runner=runner, root=tmp_path)

    assert len(observed) == len(fx["cases"]) * 3


def test_eval_real_config_cannot_use_synthetic_auto_approval(tmp_path):
    calls = []
    runner = EgressOrchestrator(
        config=Config(
            base_url="http://127.0.0.1:11434/v1",
            model="eval-model",
            data_tier="real",
        ),
        approval=SyntheticApproval(reason="must not bypass real review"),
        transport=lambda config, envelope: calls.append(envelope),
    )

    with pytest.raises(EgressApprovalError, match="requires synthetic data"):
        run_eval(_fixture(), runner=runner, root=tmp_path)

    assert calls == []
    requests = [
        EgressRequest.model_validate_json(path.read_text(encoding="utf-8"))
        for path in tmp_path.rglob("egress/*.json")
    ]
    assert len(requests) == 1
    assert requests[0].status == "prepared"
