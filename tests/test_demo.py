"""Demo skip summaries must reflect the actual missing prerequisites."""

import sys

import pytest

from scripts import demo


@pytest.mark.parametrize("approval_args", [[], ["--synthetic-auto", "--approval-reason", " "]])
def test_demo_with_key_but_missing_approval_does_not_report_missing_key(
    tmp_path, monkeypatch, capsys, approval_args
):
    for name in (
        "PSYCHTOOL_BASE_URL", "PSYCHTOOL_MODEL", "PSYCHTOOL_JUDGE_MODEL",
        "PSYCHTOOL_DATA_TIER", "PSYCHTOOL_API_KEY", "PSYCHTOOL_REDACT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PSYCHTOOL_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(sys, "argv", ["demo.py", *approval_args])
    monkeypatch.setattr(demo.tempfile, "mkdtemp", lambda: str(tmp_path))
    calls = []
    monkeypatch.setattr(demo, "http_transport", lambda config, envelope: calls.append(envelope))

    demo.main()

    output = capsys.readouterr().out
    assert "--synthetic-auto" in output
    assert "未提供密钥" not in output
    assert "未设置 PSYCHTOOL_API_KEY" not in output
    assert "synthetic-test-key" not in output
    assert calls == []
    assert list((tmp_path / "TRAIN-A" / "egress").iterdir()) == []
    assert list((tmp_path / "TRAIN-A" / "drafts").iterdir()) == []
