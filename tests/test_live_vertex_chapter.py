"""PT-24 / GROK-56: the live Vertex chapter path is manual and doubly opt-in.

Every test in this file is offline. The model call is injected as a mock and
a socket guard proves that no connection is opened; no default test in this
repository makes a live call.
"""

from __future__ import annotations

import inspect
import json
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from psychtool.config import Config
from psychtool.core.citecheck import DRAFT_FILTER_REASON
from psychtool.gateway.endpoints import VertexAuthError, vertex_openapi_base_url
from psychtool.gateway.vertex import vertex_transport
from psychtool.live import vertex_chapter
from psychtool.live.vertex_chapter import (
    DEFAULT_LOCATION,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIRNAME,
    DEFAULT_OUTPUT_FILENAME,
    DEFAULT_PROJECT,
    DEFAULT_TIMEOUT_SECONDS,
    ENV_LIVE_VERTEX,
    EXIT_REFUSED,
    LiveCaseRefused,
    LiveConfigError,
    LiveOptInError,
    LiveResponse,
    LiveTierRefused,
    LiveVertexConfig,
    check_fixture_case,
    check_live_gate,
    default_output_path,
    estimate_cost,
    estimate_prompt_tokens,
    finish_reason_name,
    format_summary,
    is_truncated_finish,
    live_generate,
    main,
    output_would_be_tracked,
    parse_live_config,
    resolve_output_path,
    response_from_sdk,
    run_live_chapter,
    sdk_generate_config,
    sdk_http_options,
    write_chapter_output,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "fixtures" / "case_a001"

_ENV_VARS = (
    "PSYCHTOOL_PROFILE",
    "PSYCHTOOL_DATA_TIER",
    "PSYCHTOOL_MODEL",
    "PSYCHTOOL_LIVE_VERTEX",
    "PSYCHTOOL_LIVE_VERTEX_MODEL",
    "PSYCHTOOL_VERTEX_PROJECT",
    "PSYCHTOOL_VERTEX_LOCATION",
    "PSYCHTOOL_VERTEX_ACCESS_TOKEN",
    "PSYCHTOOL_LIVE_VERTEX_OUTPUT",
    "PSYCHTOOL_LIVE_VERTEX_MAX_OUTPUT_TOKENS",
    "PSYCHTOOL_LIVE_VERTEX_TIMEOUT_SECONDS",
)

CITED_TEXT = (
    "Synthetic participant A reported that weekday mornings feel rushed since "
    "the semester started, but weekend routines feel unchanged. "
    "The participant logged chess club attendance for four of four scheduled "
    "meetings in October. "
    "The evaluation team scheduled a follow-up meeting."
)


@pytest.fixture(autouse=True)
def _clear_psychtool_environment(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def install_socket_guard(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access is forbidden in this test")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


class FakeGenerate:
    """A stand-in for the live model call; it records what it was asked."""

    def __init__(
        self,
        text=CITED_TEXT,
        *,
        prompt_tokens=0,
        output_tokens=0,
        total_tokens=0,
        truncated=False,
        timed_out=False,
        finish_reason=None,
        error=None,
    ):
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens
        self.truncated = truncated
        self.timed_out = timed_out
        self.finish_reason = finish_reason
        self.error = error
        self.calls: list[tuple[LiveVertexConfig, str]] = []

    def __call__(self, config: LiveVertexConfig, prompt: str) -> LiveResponse:
        self.calls.append((config, prompt))
        if self.error is not None:
            raise self.error
        return LiveResponse(
            text=self.text,
            prompt_tokens=self.prompt_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
            truncated=self.truncated,
            timed_out=self.timed_out,
            finish_reason=self.finish_reason,
        )


class RefuseGenerate:
    """Fails the test if the live path calls the model anyway."""

    def __init__(self) -> None:
        self.calls: list[tuple[LiveVertexConfig, str]] = []

    def __call__(self, config: LiveVertexConfig, prompt: str) -> LiveResponse:
        self.calls.append((config, prompt))
        raise AssertionError("the model must not be called")


def _config(**kwargs) -> LiveVertexConfig:
    values = dict(
        project=DEFAULT_PROJECT,
        location=DEFAULT_LOCATION,
        model=DEFAULT_MODEL,
        env_opt_in=True,
        cli_opt_in=True,
        profile="fake",
        data_tier="synthetic",
    )
    values.update(kwargs)
    return LiveVertexConfig(**values)


def _run(tmp_path, generate, **kwargs):
    kwargs.setdefault("config", _config())
    kwargs.setdefault("fixture_dir", FIXTURE_DIR)
    kwargs.setdefault("workdir", tmp_path)
    kwargs.setdefault("output_path", tmp_path / "chapter.txt")
    return run_live_chapter(generate=generate, **kwargs)


# --- configuration -------------------------------------------------------


def test_config_defaults_to_the_documented_project_location_and_model():
    config = parse_live_config(environ={})

    assert config.project == "fb-ailogic26vrt-3252"
    assert config.location == "global"
    assert config.model == "gemini-4-hydrogen"
    assert config.env_opt_in is False
    assert config.cli_opt_in is False
    assert config.opt_in is False
    assert config.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
    assert config.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert config.output_override is None


def test_config_reads_the_environment(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_VERTEX_PROJECT", "env-project")
    monkeypatch.setenv("PSYCHTOOL_VERTEX_LOCATION", "us-central1")
    monkeypatch.setenv("PSYCHTOOL_LIVE_VERTEX_MODEL", "gemini-4-hydrogen")
    monkeypatch.setenv(ENV_LIVE_VERTEX, "1")
    monkeypatch.setenv("PSYCHTOOL_LIVE_VERTEX_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("PSYCHTOOL_LIVE_VERTEX_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("PSYCHTOOL_LIVE_VERTEX_OUTPUT", "C:/tmp/chapter.txt")

    config = parse_live_config()

    assert config.project == "env-project"
    assert config.location == "us-central1"
    assert config.model == "gemini-4-hydrogen"
    assert config.env_opt_in is True
    assert config.cli_opt_in is False
    assert config.opt_in is False
    assert config.max_output_tokens == 2048
    assert config.timeout_seconds == 30
    assert config.output_override == "C:/tmp/chapter.txt"


def test_config_flags_win_over_the_environment(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_VERTEX_PROJECT", "env-project")
    monkeypatch.setenv("PSYCHTOOL_VERTEX_LOCATION", "us-central1")
    monkeypatch.setenv("PSYCHTOOL_MODEL", "env-model")

    monkeypatch.setenv("PSYCHTOOL_LIVE_VERTEX_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("PSYCHTOOL_LIVE_VERTEX_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("PSYCHTOOL_LIVE_VERTEX_OUTPUT", "env-out.txt")

    config = parse_live_config(
        project="flag-project",
        location="us-east1",
        model="flag-model",
        opt_in=True,
        max_output_tokens=4096,
        timeout_seconds=45,
        output="flag-out.txt",
    )

    assert config.project == "flag-project"
    assert config.location == "us-east1"
    assert config.model == "flag-model"
    assert config.cli_opt_in is True
    assert config.opt_in is False
    assert config.max_output_tokens == 4096
    assert config.timeout_seconds == 45
    assert config.output_override == "flag-out.txt"


def test_config_falls_back_to_the_product_model_variable(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_MODEL", "env-model")

    assert parse_live_config().model == "env-model"


def test_env_opt_in_flag_accepts_one(monkeypatch):
    monkeypatch.setenv(ENV_LIVE_VERTEX, "1")

    assert parse_live_config().env_opt_in is True


def test_env_opt_in_flag_ignores_other_values(monkeypatch):
    monkeypatch.setenv(ENV_LIVE_VERTEX, "0")

    assert parse_live_config().env_opt_in is False


# --- the opt-in gate -----------------------------------------------------


def test_gate_needs_the_environment_flag():
    with pytest.raises(LiveOptInError, match=ENV_LIVE_VERTEX):
        check_live_gate(_config(env_opt_in=False, cli_opt_in=True))


def test_gate_needs_the_command_line_flag():
    with pytest.raises(LiveOptInError, match="--opt-in"):
        check_live_gate(_config(env_opt_in=True, cli_opt_in=False))


def test_gate_accepts_both_opt_ins():
    check_live_gate(_config(env_opt_in=True, cli_opt_in=True))


def test_run_refuses_without_the_environment_flag(tmp_path):
    generate = RefuseGenerate()

    with pytest.raises(LiveOptInError):
        run_live_chapter(
            config=_config(env_opt_in=False, cli_opt_in=True),
            fixture_dir=FIXTURE_DIR,
            generate=generate,
            workdir=tmp_path,
            output_path=tmp_path / "chapter.txt",
        )

    assert generate.calls == []
    assert not (tmp_path / "workspace").exists()


def test_run_refuses_without_the_command_line_flag(tmp_path):
    generate = RefuseGenerate()

    with pytest.raises(LiveOptInError):
        run_live_chapter(
            config=_config(env_opt_in=True, cli_opt_in=False),
            fixture_dir=FIXTURE_DIR,
            generate=generate,
            workdir=tmp_path,
            output_path=tmp_path / "chapter.txt",
        )

    assert generate.calls == []
    assert not (tmp_path / "workspace").exists()


def test_real_profile_is_refused_even_with_both_opt_ins(tmp_path):
    generate = RefuseGenerate()

    with pytest.raises(LiveTierRefused):
        run_live_chapter(
            config=_config(profile="real"),
            fixture_dir=FIXTURE_DIR,
            generate=generate,
            workdir=tmp_path,
            output_path=tmp_path / "chapter.txt",
        )

    assert generate.calls == []


def test_real_data_tier_is_refused_even_with_both_opt_ins(tmp_path):
    generate = RefuseGenerate()

    with pytest.raises(LiveTierRefused):
        run_live_chapter(
            config=_config(data_tier="real"),
            fixture_dir=FIXTURE_DIR,
            generate=generate,
            workdir=tmp_path,
            output_path=tmp_path / "chapter.txt",
        )

    assert generate.calls == []


def test_profile_and_data_tier_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("PSYCHTOOL_PROFILE", "real")
    monkeypatch.setenv(ENV_LIVE_VERTEX, "1")

    config = parse_live_config(opt_in=True)

    assert config.profile == "real"
    with pytest.raises(LiveTierRefused):
        check_live_gate(config)


# --- the fixture case ----------------------------------------------------


def test_fixture_case_is_the_synthetic_case_a001():
    assert check_fixture_case(FIXTURE_DIR) == "case-a001"


def test_another_case_is_refused(tmp_path):
    other = tmp_path / "case_b002"
    shutil.copytree(FIXTURE_DIR, other)
    meta = json.loads((other / "meta.json").read_text(encoding="utf-8"))
    meta["case_id"] = "case-b002"
    (other / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(LiveCaseRefused):
        check_fixture_case(other)


def test_a_non_synthetic_tier_is_refused(tmp_path):
    other = tmp_path / "case-a001-real"
    shutil.copytree(FIXTURE_DIR, other)
    meta = json.loads((other / "meta.json").read_text(encoding="utf-8"))
    meta["data_tier"] = "real"
    (other / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(LiveCaseRefused):
        check_fixture_case(other)


def test_the_repository_fixture_is_never_written(tmp_path):
    generate = FakeGenerate()

    run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )

    assert (tmp_path / "workspace" / "materials" / "m1.v1.json").is_file()
    assert not (FIXTURE_DIR / "claims").exists()
    assert not (FIXTURE_DIR / "evidence").exists()


# --- one mocked chapter --------------------------------------------------


def test_mocked_chapter_counts_cited_and_uncited_sentences(tmp_path, monkeypatch):
    install_socket_guard(monkeypatch)
    generate = FakeGenerate(
        CITED_TEXT, prompt_tokens=800, output_tokens=200, total_tokens=1000
    )

    result = run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )

    assert result.case_id == "case-a001"
    assert result.section_id == "history"
    assert result.model == DEFAULT_MODEL
    assert result.location == DEFAULT_LOCATION
    assert result.project == DEFAULT_PROJECT
    assert result.total_sentences == 3
    assert result.cited_sentences == 2
    assert result.uncited_sentences == 1
    assert result.guard_blocked is False
    assert result.status == "PASS"
    assert result.prompt_tokens == 800
    assert result.output_tokens == 200
    assert result.total_tokens == 1000


def test_mocked_chapter_prompt_carries_the_fixture_statements(tmp_path):
    generate = FakeGenerate()

    run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )

    prompt = generate.calls[0][1]
    assert "weekday mornings feel rushed" in prompt
    assert "chess club attendance" in prompt
    assert "History section" in prompt


def test_the_guard_blocks_diagnostic_wording(tmp_path):
    generate = FakeGenerate("The participant meets criteria for a disorder.")

    result = run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )

    assert result.guard_blocked is True
    assert result.guard_reason == DRAFT_FILTER_REASON
    assert result.status == "FAIL"


def test_the_summary_reports_counts_guard_tokens_and_cost(tmp_path):
    generate = FakeGenerate(
        CITED_TEXT, prompt_tokens=800, output_tokens=200, total_tokens=1000
    )

    result = run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )
    summary = format_summary(result)

    assert "sentences: 3 (cited 2, uncited 1)" in summary
    assert "guard: PASS" in summary
    assert "tokens: prompt 800, output 200, total 1000" in summary
    assert "cost actual: US$0.0027" in summary
    assert "cost worst-case at cap:" in summary
    assert f"cap: max_output_tokens={DEFAULT_MAX_OUTPUT_TOKENS}" in summary
    assert f"timeout={DEFAULT_TIMEOUT_SECONDS}s" in summary
    assert "output:" in summary
    assert "chapter.txt" in summary
    assert "RESULT: PASS" in summary


# --- cost ----------------------------------------------------------------


def test_cost_uses_the_published_global_rate():
    estimate = estimate_cost(
        model="gemini-4-hydrogen",
        location="global",
        prompt_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert estimate.amount == pytest.approx(9.00)
    assert estimate.label == "US$9.0000"
    assert "Model Garden pricing page" in estimate.note


def test_cost_is_unknown_for_another_model():
    estimate = estimate_cost(
        model="gemini-2.0-flash",
        location="global",
        prompt_tokens=1000,
        output_tokens=1000,
    )

    assert estimate.amount is None
    assert estimate.label == "unknown"


def test_cost_is_unknown_outside_global():
    estimate = estimate_cost(
        model="gemini-4-hydrogen",
        location="us-central1",
        prompt_tokens=1000,
        output_tokens=1000,
    )

    assert estimate.amount is None
    assert estimate.label == "unknown"


# --- the command line ----------------------------------------------------


def test_the_command_refuses_without_both_opt_ins(monkeypatch, capsys):
    assert main([]) == EXIT_REFUSED
    assert "refused" in capsys.readouterr().err


def test_the_command_refuses_the_real_profile(monkeypatch, capsys):
    monkeypatch.setenv("PSYCHTOOL_PROFILE", "real")
    monkeypatch.setenv(ENV_LIVE_VERTEX, "1")

    assert main(["--opt-in"]) == EXIT_REFUSED
    assert "refused" in capsys.readouterr().err


# --- the SDK stays optional ----------------------------------------------


def test_the_sdk_is_imported_only_inside_the_live_call():
    source = Path(vertex_chapter.__file__).read_text(encoding="utf-8")

    assert source.count("from google import genai") == 1
    assert "from google import genai" in inspect.getsource(live_generate)


def test_the_existing_vertex_transport_still_refuses_adc(monkeypatch):
    install_socket_guard(monkeypatch)
    config = Config(
        base_url=vertex_openapi_base_url("synthetic-proj", "us-central1"),
        model="gemini-2.0-flash",
        data_tier="synthetic",
        transport="vertex",
        profile="vertex",
    )

    with pytest.raises(VertexAuthError, match="are not probed"):
        vertex_transport(config, {"model": "gemini-2.0-flash", "messages": []})



def test_live_generate_refuses_before_importing_the_sdk():
    with pytest.raises(LiveOptInError, match="PSYCHTOOL_LIVE_VERTEX"):
        live_generate(_config(env_opt_in=False, cli_opt_in=True), "do not call the model")



# --- caps and output file ------------------------------------------------


def test_invalid_caps_are_refused():
    with pytest.raises(LiveConfigError, match="max_output_tokens"):
        parse_live_config(max_output_tokens=0)
    with pytest.raises(LiveConfigError, match="max_output_tokens"):
        parse_live_config(max_output_tokens="abc")
    with pytest.raises(LiveConfigError, match="timeout_seconds"):
        parse_live_config(timeout_seconds=-1)
    with pytest.raises(LiveConfigError, match="timeout_seconds"):
        parse_live_config(timeout_seconds="900")


def test_the_cap_is_wired_into_the_sdk_options():
    config = _config(max_output_tokens=2048, timeout_seconds=30)
    http = sdk_http_options(config)
    generate = sdk_generate_config(config)

    assert http["timeout"] == 30_000
    assert http["retry_options"] == {"attempts": 1}
    assert generate["max_output_tokens"] == 2048
    assert generate["http_options"] == http


def test_live_generate_source_passes_the_cap_helpers():
    source = inspect.getsource(live_generate)

    assert "sdk_generate_config(config)" in source
    assert "sdk_http_options(config)" in source
    assert "max_output_tokens=generate_kwargs[\"max_output_tokens\"]" in source
    assert "http_options=http_options" in source


def test_response_from_sdk_marks_a_truncated_finish():
    response = SimpleNamespace(
        text="partial chapter.",
        usage_metadata=SimpleNamespace(
            prompt_token_count=100,
            candidates_token_count=50,
            thoughts_token_count=0,
            total_token_count=150,
        ),
        candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
    )

    result = response_from_sdk(response)

    assert result.truncated is True
    assert result.timed_out is False
    assert finish_reason_name(response) == "MAX_TOKENS"
    assert is_truncated_finish(result.finish_reason) is True
    assert result.output_tokens == 50


def test_a_truncated_response_fails_and_still_runs_the_guard(tmp_path):
    generate = FakeGenerate(
        CITED_TEXT,
        prompt_tokens=800,
        output_tokens=8192,
        total_tokens=8992,
        truncated=True,
        finish_reason="MAX_TOKENS",
    )

    result = run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )
    summary = format_summary(result)

    assert result.truncated is True
    assert result.status == "FAIL"
    assert result.guard_blocked is False
    assert result.cited_sentences == 2
    assert "response truncated at max_output_tokens=8192" in summary
    assert "guard: PASS" in summary
    assert (tmp_path / "chapter.txt").read_text(encoding="utf-8") == CITED_TEXT


def test_a_timeout_fails_and_still_runs_the_guard(tmp_path):
    generate = FakeGenerate("partial sentence.", timed_out=True, prompt_tokens=0, output_tokens=0)

    result = run_live_chapter(
        config=_config(timeout_seconds=15),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )
    summary = format_summary(result)

    assert result.timed_out is True
    assert result.status == "FAIL"
    assert "request timed out after 15s" in summary
    assert "guard:" in summary
    assert (tmp_path / "chapter.txt").read_text(encoding="utf-8") == "partial sentence."


def test_a_timeout_exception_is_converted_and_checked(tmp_path):
    generate = FakeGenerate(error=TimeoutError("the request timed out"))

    result = run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )

    assert result.timed_out is True
    assert result.status == "FAIL"
    assert result.text == ""
    assert (tmp_path / "chapter.txt").read_text(encoding="utf-8") == ""
    assert "request timed out after" in format_summary(result)


def test_worst_case_cost_uses_the_output_cap_not_actual_usage():
    estimated_prompt = estimate_prompt_tokens("abcd" * 100)
    assert estimated_prompt == 100

    worst = estimate_cost(
        model="gemini-4-hydrogen",
        location="global",
        prompt_tokens=estimated_prompt,
        output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
    )
    actual = estimate_cost(
        model="gemini-4-hydrogen",
        location="global",
        prompt_tokens=800,
        output_tokens=200,
    )

    # 100 * 1.50 / 1e6 + 8192 * 7.50 / 1e6
    assert worst.amount == pytest.approx((100 * 1.50 + 8192 * 7.50) / 1_000_000)
    assert actual.amount == pytest.approx(0.0027)
    assert worst.amount > actual.amount


def test_mocked_chapter_reports_worst_case_cost_at_the_cap(tmp_path):
    generate = FakeGenerate(
        CITED_TEXT, prompt_tokens=800, output_tokens=200, total_tokens=1000
    )

    result = run_live_chapter(
        config=_config(max_output_tokens=4096),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path,
        output_path=tmp_path / "chapter.txt",
    )

    assert result.estimated_prompt_tokens == estimate_prompt_tokens(generate.calls[0][1])
    assert result.cost.amount == pytest.approx(0.0027)
    assert result.cost_worst_case.amount == pytest.approx(
        (
            result.estimated_prompt_tokens * 1.50
            + 4096 * 7.50
        )
        / 1_000_000
    )
    summary = format_summary(result)
    assert "cost worst-case at cap:" in summary
    assert "output at cap 4096" in summary
    assert "cost actual: US$0.0027" in summary


def test_default_output_path_is_gitignored():
    import subprocess

    path = default_output_path()

    assert DEFAULT_OUTPUT_DIRNAME.replace("\\", "/") in path.as_posix()
    assert path.name == DEFAULT_OUTPUT_FILENAME
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path)],
        cwd=REPO,
        check=False,
    )
    assert result.returncode == 0
    assert output_would_be_tracked(path, REPO) is False


def test_the_chapter_text_is_written_and_the_absolute_path_is_reported(tmp_path):
    generate = FakeGenerate(CITED_TEXT)
    output = tmp_path / "out" / "history.txt"

    result = run_live_chapter(
        config=_config(),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path / "work",
        output_path=output,
    )
    summary = format_summary(result)

    assert output.is_file()
    assert output.read_text(encoding="utf-8") == CITED_TEXT
    assert result.output_path == str(output.resolve())
    assert str(output.resolve()) in summary
    assert Path(result.output_path).is_absolute()


def test_output_override_from_config_is_used(tmp_path):
    generate = FakeGenerate(CITED_TEXT)
    dest = tmp_path / "from-config.txt"

    result = run_live_chapter(
        config=_config(output_override=str(dest)),
        fixture_dir=FIXTURE_DIR,
        generate=generate,
        workdir=tmp_path / "work",
    )

    assert dest.read_text(encoding="utf-8") == CITED_TEXT
    assert result.output_path == str(dest.resolve())


def test_a_directory_override_gets_the_default_filename(tmp_path):
    path = resolve_output_path(str(tmp_path) + "/", case_id="case-a001", section_id="history")

    assert path == (tmp_path / "case-a001-history.txt").resolve()


def test_a_tracked_output_path_is_refused(tmp_path):
    tracked = REPO / "README.md"

    with pytest.raises(LiveConfigError, match="not gitignored"):
        write_chapter_output(tracked, "should not be written", repo=REPO)
    # the existing README is left untouched
    assert "should not be written" not in tracked.read_text(encoding="utf-8")


def test_the_gate_does_not_write_an_output_file(tmp_path):
    dest = tmp_path / "should-not-exist.txt"
    generate = RefuseGenerate()

    with pytest.raises(LiveOptInError):
        run_live_chapter(
            config=_config(env_opt_in=False, cli_opt_in=True),
            fixture_dir=FIXTURE_DIR,
            generate=generate,
            workdir=tmp_path / "work",
            output_path=dest,
        )

    assert not dest.exists()
