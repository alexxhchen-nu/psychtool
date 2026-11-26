"""CLI model workflows must use persisted egress approval requests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import psychtool.cli.app as cli_module
from psychtool.cli.app import app
from psychtool.core.claims import add_claim
from psychtool.core.egress import EgressRequest, canonical_hash, save_egress_request
from psychtool.core.workspace import import_material, init_workspace, set_known_names

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


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    workspace = init_workspace(tmp_path / "case-a", case_id="case-a")
    import_material(
        workspace, material_id="doc-1", title="Synthetic source",
        provider="synthetic", date="synthetic date", text="Synthetic observation.",
    )
    add_claim(
        workspace,
        claim_id="c1",
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="synthetic intake",
        record_time="synthetic date",
        category="client_statement",
        topic="history",
        text="Synthetic observation.",
    )
    return workspace


def _configure(monkeypatch, *, tier: str) -> None:
    monkeypatch.setenv("PSYCHTOOL_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("PSYCHTOOL_MODEL", "draft-model")
    monkeypatch.setenv("PSYCHTOOL_JUDGE_MODEL", "judge-model")
    monkeypatch.setenv("PSYCHTOOL_DATA_TIER", tier)
    monkeypatch.setenv("PSYCHTOOL_API_KEY", "api-key-must-not-leak")


def _requests(workspace: Path) -> list[EgressRequest]:
    return [
        EgressRequest.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((workspace / "egress").glob("*.json"))
    ]


def test_real_draft_without_reviewer_stays_prepared_and_does_not_send(
    ws, runner, monkeypatch
):
    _configure(monkeypatch, tier="real")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope))

    result = runner.invoke(
        app,
        ["draft", str(ws), "--claim-ids", "c1", "--instructions", "Write background."],
    )

    assert result.exit_code != 0
    requests = _requests(ws)
    assert len(requests) == 1
    assert requests[0].status == "prepared"
    assert calls == []
    assert requests[0].request_id in result.output
    assert requests[0].content_hash in result.output
    assert "status: prepared" in result.output
    assert "api-key-must-not-leak" not in result.output


def test_cli_preview_is_redacted_and_never_prints_raw_identifiers(
    ws, runner, monkeypatch
):
    _configure(monkeypatch, tier="real")
    set_known_names(ws, ["Jane Doe"])
    add_claim(
        ws,
        claim_id="c2",
        source_document_id="doc-1",
        source_version=1,
        source_passage_id="p002",
        provider_role="self_report",
        observation_setting="intake",
        record_time="synthetic date",
        category="client_statement",
        topic="contact",
        text="Jane Doe called 312-555-0142.",
    )
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: "unused")

    result = runner.invoke(
        app,
        ["draft", str(ws), "--claim-ids", "c2", "--instructions", "Write background."],
    )

    assert result.exit_code != 0
    assert "Jane Doe" not in result.output
    assert "312-555-0142" not in result.output
    assert "[[NAME_" in result.output
    assert "[[TELEPHONE_" in result.output
    assert "api-key-must-not-leak" not in result.output


def test_synthetic_draft_requires_explicit_auto_approval(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="synthetic")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope))

    result = runner.invoke(
        app,
        ["draft", str(ws), "--claim-ids", "c1", "--instructions", "Write background."],
    )

    assert result.exit_code != 0
    assert calls == []
    assert _requests(ws)[0].status == "prepared"


def test_draft_max_cost_fails_before_request_or_transport(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="synthetic")
    calls = []
    monkeypatch.setattr(
        cli_module,
        "_cli_transport",
        lambda config, envelope: calls.append(envelope),
    )

    result = runner.invoke(
        app,
        [
            "draft",
            str(ws),
            "--claim-ids",
            "c1",
            "--instructions",
            "Write background.",
            "--max-cost",
            "1.0",
            "--synthetic-auto",
            "--approval-reason",
            "frozen synthetic fixture",
        ],
    )

    assert result.exit_code != 0
    assert "strict egress runner does not support cost enforcement" in result.output
    assert calls == []
    assert _requests(ws) == []
    assert not (ws / "drafts" / "d1.v1.json").exists()


def test_synthetic_draft_auto_approval_with_reason_sends(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="synthetic")
    observed_statuses = []

    def transport(config, envelope):
        request = _requests(ws)[0]
        observed_statuses.append(request.status)
        assert request.approval_mode == "synthetic_auto"
        assert request.approval_reason == "frozen synthetic fixture"
        return "Synthetic draft text."

    monkeypatch.setattr(cli_module, "_cli_transport", transport)
    result = runner.invoke(
        app,
        [
            "draft",
            str(ws),
            "--claim-ids",
            "c1",
            "--instructions",
            "Write background.",
            "--synthetic-auto",
            "--approval-reason",
            "frozen synthetic fixture",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed_statuses == ["approved"]
    assert _requests(ws)[0].status == "sent"
    assert (ws / "drafts" / "d1.v1.json").is_file()


def test_synthetic_cli_binds_approval_to_displayed_hash(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="synthetic")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope) or "Clean output.")
    show_prepared = cli_module._show_prepared_request

    def replace_after_display(request):
        show_prepared(request)
        changed = request.model_copy(deep=True)
        changed.envelope.messages[0]["content"] = "Changed synthetic prompt."
        changed = changed.model_copy(update={"content_hash": canonical_hash(changed)})
        save_egress_request(ws, changed)

    monkeypatch.setattr(cli_module, "_show_prepared_request", replace_after_display)
    result = runner.invoke(app, [
        "draft", str(ws), "--claim-ids", "c1", "--instructions", "Draft.",
        "--synthetic-auto", "--approval-reason", "synthetic fixture",
    ])

    assert result.exit_code != 0
    assert calls == []
    request = _requests(ws)[0]
    assert request.status == "invalidated"
    assert request.approval_mode is None
    assert list((ws / "drafts").iterdir()) == []


def test_real_draft_confirmation_sends_human_approved_request(
    ws, runner, monkeypatch
):
    _configure(monkeypatch, tier="real")
    observed = []

    def transport(config, envelope):
        request = _requests(ws)[0]
        observed.append((request.status, request.approval_mode, request.reviewer))
        return "Confirmed draft."

    monkeypatch.setattr(cli_module, "_cli_transport", transport)
    result = runner.invoke(
        app,
        [
            "draft",
            str(ws),
            "--claim-ids",
            "c1",
            "--instructions",
            "Write background.",
            "--reviewer",
            "reviewer-1",
        ],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert observed == [("approved", "human", "reviewer-1")]
    assert _requests(ws)[0].status == "sent"


def test_real_draft_rejection_leaves_request_prepared(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="real")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope))

    result = runner.invoke(
        app,
        [
            "draft",
            str(ws),
            "--claim-ids",
            "c1",
            "--instructions",
            "Write background.",
            "--reviewer",
            "reviewer-1",
        ],
        input="n\n",
    )

    assert result.exit_code != 0
    assert calls == []
    assert _requests(ws)[0].status == "prepared"


def test_real_draft_eof_leaves_request_prepared(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="real")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope))

    result = runner.invoke(
        app,
        [
            "draft",
            str(ws),
            "--claim-ids",
            "c1",
            "--instructions",
            "Write background.",
            "--reviewer",
            "reviewer-1",
        ],
        input="",
    )

    assert result.exit_code != 0
    assert calls == []
    assert _requests(ws)[0].status == "prepared"


def test_draft_rejects_mixed_real_and_synthetic_options(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="synthetic")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope))

    result = runner.invoke(
        app,
        [
            "draft",
            str(ws),
            "--claim-ids",
            "c1",
            "--instructions",
            "Write background.",
            "--reviewer",
            "reviewer-1",
            "--synthetic-auto",
            "--approval-reason",
            "fixture",
        ],
    )

    assert result.exit_code != 0
    assert calls == []
    assert _requests(ws) == []


def test_eval_cli_requires_explicit_synthetic_approval(runner, monkeypatch):
    _configure(monkeypatch, tier="synthetic")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope))
    fixture = Path(__file__).parent.parent / "fixtures" / "adolescent-background.json"

    result = runner.invoke(app, ["eval", "--fixture", str(fixture)])

    assert result.exit_code != 0
    assert calls == []


def test_eval_cli_rejects_real_config_auto_approval(runner, monkeypatch):
    _configure(monkeypatch, tier="real")
    calls = []
    monkeypatch.setattr(cli_module, "_cli_transport", lambda config, envelope: calls.append(envelope))
    fixture = Path(__file__).parent.parent / "fixtures" / "adolescent-background.json"

    result = runner.invoke(
        app,
        [
            "eval",
            "--fixture",
            str(fixture),
            "--synthetic-auto",
            "--approval-reason",
            "fixture",
        ],
    )

    assert result.exit_code != 0
    assert calls == []


def test_judge_uses_judge_model_and_approved_request(ws, runner, monkeypatch):
    _configure(monkeypatch, tier="synthetic")
    (ws / "drafts" / "d1.v1.json").write_text(
        json.dumps(
            {
                "id": "d1",
                "case_id": "case-a",
                "version": 1,
                "claim_ids": ["c1"],
                "text": "Synthetic draft text.",
                "citations": [
                    {
                        "claim_id": "c1",
                        "claim_version": 1,
                        "source_document_id": "doc-1",
                        "source_version": 1,
                        "source_passage_id": "p001",
                        "statement": "Synthetic observation.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def transport(config, envelope):
        assert config.model == "judge-model"
        request = _requests(ws)[0]
        assert request.status == "approved"
        assert {ref.kind for ref in request.source_refs} == {"draft", "claim"}
        return '{"verdict":"supported","explanation":"ok"}'

    monkeypatch.setattr(cli_module, "_cli_transport", transport)
    result = runner.invoke(
        app,
        [
            "judge",
            str(ws),
            "--draft-id",
            "d1",
            "--synthetic-auto",
            "--approval-reason",
            "synthetic review",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _requests(ws)[0].status == "sent"
