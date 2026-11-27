"""Generate one History chapter from the synthetic fixture on Vertex AI.

PT-24 / GROK-56, ADR 0024. This module is a **separate** live path: it does
not touch the existing Vertex transport in :mod:`psychtool.gateway.vertex`,
so ADR 0022 is unchanged — that transport still refuses to probe Application
Default Credentials, and the ``real`` profile still refuses every non-local
endpoint.

The rules this path enforces:

- the run is refused unless **both** opt-ins are present: the environment
  flag ``PSYCHTOOL_LIVE_VERTEX=1`` and the command-line flag ``--opt-in``.
  The refusal happens before any client is constructed;
- ``PSYCHTOOL_PROFILE=real`` or ``PSYCHTOOL_DATA_TIER=real`` is refused
  even with both opt-ins;
- only the synthetic fixture case ``case-a001`` may be used. The fixture is
  copied into a scratch workspace, so the repository copy is never written;
- the chapter is checked with the existing sentence citation check
  (:func:`psychtool.core.citecheck.citecheck_text`) and the existing R7
  wording guard (:func:`psychtool.core.citecheck.check_draft_text`). The
  text is never rewritten;
- the generated text is written to a local file (default:
  ``local-data/live-vertex/case-a001-history.txt``, which is gitignored)
  and the absolute path is printed. A flag or environment variable can
  override the path; a path inside the repository that is not gitignored
  is refused;
- ``max_output_tokens`` and the request timeout are always sent to the
  google-genai call. The summary prints a pre-call worst-case cost at
  the output cap, then the actual cost from reported usage. A truncated
  or timed-out response is a FAIL, and the guard and citation checks
  still run on whatever text came back.

The google-genai SDK is an optional extra (``live``) and is imported only
inside :func:`live_generate`, so the default test run never needs it and no
test in this repository makes a live call.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from psychtool.config import (
    DEFAULT_DATA_TIER,
    DEFAULT_PROFILE,
    ENV_DATA_TIER,
    ENV_MODEL,
    ENV_PROFILE,
    ENV_VERTEX_LOCATION,
    ENV_VERTEX_PROJECT,
)
from psychtool.core.citecheck import (
    SentenceEvidence,
    check_draft_text,
    citecheck_text,
)
from psychtool.core.evidence_store import ensure_material_evidence
from psychtool.core.extract import RuleExtractor
from psychtool.core.intake_claims import accept_suggestion, suggest_claims
from psychtool.core.report_templates import (
    is_clinician_authored_section,
    load_template,
)
from psychtool.core.sections import build_section_request_input
from psychtool.core.workspace import Material, list_materials

ENV_LIVE_VERTEX = "PSYCHTOOL_LIVE_VERTEX"
ENV_LIVE_VERTEX_MODEL = "PSYCHTOOL_LIVE_VERTEX_MODEL"
ENV_LIVE_VERTEX_OUTPUT = "PSYCHTOOL_LIVE_VERTEX_OUTPUT"
ENV_LIVE_VERTEX_MAX_OUTPUT_TOKENS = "PSYCHTOOL_LIVE_VERTEX_MAX_OUTPUT_TOKENS"
ENV_LIVE_VERTEX_TIMEOUT_SECONDS = "PSYCHTOOL_LIVE_VERTEX_TIMEOUT_SECONDS"

DEFAULT_PROJECT = "fb-ailogic26vrt-3252"
DEFAULT_LOCATION = "global"
DEFAULT_MODEL = "gemini-4-hydrogen"
DEFAULT_TEMPLATE_ID = "intake-report"
DEFAULT_SECTION_ID = "history"
DEFAULT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_TIMEOUT_SECONDS = 120
MAX_ALLOWED_OUTPUT_TOKENS = 65536
MAX_ALLOWED_TIMEOUT_SECONDS = 600
PROMPT_CHARS_PER_TOKEN = 4
DEFAULT_OUTPUT_DIRNAME = "local-data/live-vertex"
DEFAULT_OUTPUT_FILENAME = "case-a001-history.txt"

ALLOWED_CASE_IDS = frozenset({"case-a001"})

PRICED_MODEL = DEFAULT_MODEL
PRICED_LOCATION = DEFAULT_LOCATION
INPUT_PRICE_PER_MILLION = 1.50
OUTPUT_PRICE_PER_MILLION = 7.50

EXIT_OK = 0
EXIT_GUARD_BLOCKED = 1
EXIT_REFUSED = 2

DEFAULT_INSTRUCTIONS = (
    "Write the History section of the intake report for this synthetic case. "
    "Use only the candidate statements listed below and do not add outside "
    "knowledge. Keep every attribution (self report, other report, professional "
    "summary) and keep conflicting accounts side by side instead of resolving "
    "them. Say 'unknown' for anything the statements do not cover. Do not state "
    "a diagnosis, a score, a norm or a recommendation. Repeat the wording of the "
    "statement each sentence comes from so that every sentence can be matched "
    "back to its source."
)


class LiveChapterError(RuntimeError):
    """Base class for every refusal raised by the live path."""


class LiveOptInError(LiveChapterError):
    """Raised when the environment flag or the command-line flag is missing."""


class LiveTierRefused(LiveChapterError):
    """Raised when the profile or the data tier is ``real``."""


class LiveCaseRefused(LiveChapterError):
    """Raised for any case other than the synthetic fixture case."""


class LiveConfigError(LiveChapterError):
    """Raised when a cap, timeout, or output path cannot be used."""


@dataclass(frozen=True)
class LiveVertexConfig:
    """Everything the live path needs, resolved from flags and environment."""

    project: str = DEFAULT_PROJECT
    location: str = DEFAULT_LOCATION
    model: str = DEFAULT_MODEL
    env_opt_in: bool = False
    cli_opt_in: bool = False
    profile: str = DEFAULT_PROFILE
    data_tier: str = DEFAULT_DATA_TIER
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    output_override: str | None = None

    @property
    def opt_in(self) -> bool:
        """True only when the environment flag *and* the flag are present."""
        return self.env_opt_in and self.cli_opt_in


@dataclass(frozen=True)
class LiveResponse:
    """The generated text plus the token usage reported by the model."""

    text: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    truncated: bool = False
    timed_out: bool = False
    finish_reason: str | None = None


@dataclass(frozen=True)
class CostEstimate:
    """A cost estimate, or an explicit ``unknown``."""

    amount: float | None
    label: str
    note: str


@dataclass(frozen=True)
class LiveChapterResult:
    """The outcome of one live (or mocked) chapter run."""

    case_id: str
    section_id: str
    project: str
    location: str
    model: str
    text: str
    total_sentences: int
    cited_sentences: int
    uncited_sentences: int
    guard_blocked: bool
    guard_reason: str | None
    prompt_tokens: int
    output_tokens: int
    total_tokens: int
    cost: CostEstimate
    cost_worst_case: CostEstimate
    estimated_prompt_tokens: int = 0
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    truncated: bool = False
    timed_out: bool = False
    finish_reason: str | None = None
    output_path: str | None = None

    @property
    def fail_reasons(self) -> list[str]:
        """Why the run is a FAIL, in a stable order."""
        reasons: list[str] = []
        if self.timed_out:
            reasons.append(f"request timed out after {self.timeout_seconds}s")
        if self.truncated:
            reasons.append(
                f"response truncated at max_output_tokens={self.max_output_tokens}"
            )
        if self.guard_blocked:
            reasons.append(self.guard_reason or "guard blocked")
        return reasons

    @property
    def status(self) -> str:
        """``PASS`` only when the cap held and the wording guard is clean."""
        return "FAIL" if self.fail_reasons else "PASS"


GenerateCallable = Callable[[LiveVertexConfig, str], LiveResponse]


def _env_flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_bounded_int(
    raw: object,
    *,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Parse a positive integer flag or environment value, or return the default."""
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        raise LiveConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < minimum or value > maximum:
        raise LiveConfigError(
            f"{name} must be between {minimum} and {maximum}, got {value}"
        )
    return value


def parse_live_config(
    *,
    project: str | None = None,
    location: str | None = None,
    model: str | None = None,
    opt_in: bool = False,
    max_output_tokens: int | str | None = None,
    timeout_seconds: int | str | None = None,
    output: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> LiveVertexConfig:
    """Resolve the live configuration from flags and environment variables.

    Precedence: command-line flag, then environment variable, then default.
    The project defaults to ``fb-ailogic26vrt-3252``, the location to
    ``global`` and the model to ``gemini-4-hydrogen``. The model environment
    variable is ``PSYCHTOOL_LIVE_VERTEX_MODEL``; ``PSYCHTOOL_MODEL`` is used
    as a fallback so the live path follows the same model setting as the
    rest of the product. ``max_output_tokens`` defaults to 8192 and the
    request timeout to 120 seconds.
    """
    env = os.environ if environ is None else environ
    resolved_project = (project or env.get(ENV_VERTEX_PROJECT) or "").strip()
    resolved_location = (location or env.get(ENV_VERTEX_LOCATION) or "").strip()
    resolved_model = (
        model or env.get(ENV_LIVE_VERTEX_MODEL) or env.get(ENV_MODEL) or ""
    ).strip()
    resolved_output = (output if output is not None else env.get(ENV_LIVE_VERTEX_OUTPUT) or "").strip()
    token_raw = (
        max_output_tokens
        if max_output_tokens is not None
        else env.get(ENV_LIVE_VERTEX_MAX_OUTPUT_TOKENS)
    )
    timeout_raw = (
        timeout_seconds
        if timeout_seconds is not None
        else env.get(ENV_LIVE_VERTEX_TIMEOUT_SECONDS)
    )
    return LiveVertexConfig(
        project=resolved_project or DEFAULT_PROJECT,
        location=resolved_location or DEFAULT_LOCATION,
        model=resolved_model or DEFAULT_MODEL,
        env_opt_in=_env_flag(env.get(ENV_LIVE_VERTEX)),
        cli_opt_in=bool(opt_in),
        profile=(env.get(ENV_PROFILE) or DEFAULT_PROFILE).strip().lower(),
        data_tier=(env.get(ENV_DATA_TIER) or DEFAULT_DATA_TIER).strip().lower(),
        max_output_tokens=_parse_bounded_int(
            token_raw,
            name="max_output_tokens",
            default=DEFAULT_MAX_OUTPUT_TOKENS,
            minimum=1,
            maximum=MAX_ALLOWED_OUTPUT_TOKENS,
        ),
        timeout_seconds=_parse_bounded_int(
            timeout_raw,
            name="timeout_seconds",
            default=DEFAULT_TIMEOUT_SECONDS,
            minimum=1,
            maximum=MAX_ALLOWED_TIMEOUT_SECONDS,
        ),
        output_override=resolved_output or None,
    )


def check_live_gate(config: LiveVertexConfig) -> None:
    """Refuse unless the tier is synthetic and both opt-ins are present.

    The order is fixed: a ``real`` profile or data tier is refused first
    (that refusal holds with or without the opt-ins), then the environment
    flag, then the command-line flag. Every refusal happens before a client
    is constructed.
    """
    if config.profile == "real" or config.data_tier == "real":
        raise LiveTierRefused(
            "the live Vertex path refuses profile/data_tier 'real': real case "
            "data never leaves this machine"
        )
    if not config.env_opt_in:
        raise LiveOptInError(
            f"the live Vertex path requires {ENV_LIVE_VERTEX}=1 in the environment"
        )
    if not config.cli_opt_in:
        raise LiveOptInError(
            "the live Vertex path requires the --opt-in flag on the command line"
        )


def default_fixture_dir() -> Path:
    """The repository's synthetic fixture case."""
    return Path(__file__).resolve().parents[2] / "fixtures" / "case_a001"


def check_fixture_case(fixture_dir: Path) -> str:
    """Return the case id of the permitted synthetic fixture, else refuse."""
    fixture_dir = Path(fixture_dir)
    meta_path = fixture_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LiveCaseRefused(
            f"no meta.json in {fixture_dir}: only the synthetic fixture case may be used"
        ) from None
    except json.JSONDecodeError:
        raise LiveCaseRefused(
            f"meta.json in {fixture_dir} is not readable: only the synthetic "
            "fixture case may be used"
        ) from None
    if not isinstance(meta, dict):
        raise LiveCaseRefused(
            f"meta.json in {fixture_dir} is not a case description: only the "
            "synthetic fixture case may be used"
        )
    case_id = meta.get("case_id")
    data_tier = meta.get("data_tier", DEFAULT_DATA_TIER)
    if data_tier != "synthetic":
        raise LiveCaseRefused(
            f"the live Vertex path only accepts the synthetic tier; {fixture_dir} "
            f"is marked {data_tier!r}"
        )
    if case_id not in ALLOWED_CASE_IDS:
        raise LiveCaseRefused(
            f"the live Vertex path only accepts the synthetic fixture case; "
            f"{fixture_dir} holds case {case_id!r}"
        )
    return str(case_id)


def prepare_workspace(fixture_dir: Path, destination: Path) -> Path:
    """Copy the fixture into a scratch workspace; the repo copy is never written."""
    destination = Path(destination)
    if destination.exists():
        raise LiveCaseRefused(f"workspace destination already exists: {destination}")
    shutil.copytree(Path(fixture_dir), destination)
    for sub in ("claims", "drafts", "reviews", "egress"):
        (destination / sub).mkdir(exist_ok=True)
    return destination


def provider_role_for(material: Material) -> str:
    """The attribution role for one material, from its title and provider."""
    haystack = f"{material.title} {material.provider}".lower()
    if "caregiver" in haystack or "school" in haystack or "teacher" in haystack:
        return "other_report"
    if "summary" in haystack or "clinician" in haystack or "evaluator" in haystack:
        return "clinician_interpretation"
    return "self_report"


def extract_evidence(workspace: Path, case_id: str) -> list[dict]:
    """Extract and persist the sentence evidence of every material."""
    rows: list[dict] = []
    for material in list_materials(workspace):
        rows.extend(
            ensure_material_evidence(workspace, case_id, material, RuleExtractor())
        )
    return rows


def build_claims(workspace: Path, materials: list[Material]) -> list[str]:
    """Accept one claim per passage that carries stored sentence evidence."""
    claim_ids: list[str] = []
    for material in materials:
        suggestions = suggest_claims(
            workspace,
            material.id,
            provider_role=provider_role_for(material),
        )
        for suggestion in suggestions:
            claim_ids.append(accept_suggestion(workspace, suggestion).id)
    return claim_ids


def uploaded_texts(workspace: Path) -> list[str]:
    """Every uploaded passage text (the R7 manual-text allowlist)."""
    return [
        passage.text
        for material in list_materials(workspace)
        for passage in material.passages
    ]


def sentence_evidence(rows: list[dict]) -> list[SentenceEvidence]:
    """Active evidence rows as citation-check inputs."""
    return [
        SentenceEvidence(evidence_id=row["evidence_id"], quote=row["quote"])
        for row in rows
        if row.get("status") == "active"
    ]


def estimate_cost(
    *,
    model: str,
    location: str,
    prompt_tokens: int,
    output_tokens: int,
) -> CostEstimate:
    """Estimate the cost of one call, or report it as unknown.

    The rate is the Standard PayGo Global list price for Gemini 4 Hydrogen:
    input US$1.50 per million tokens, output (response and reasoning)
    US$7.50 per million tokens (Model Garden pricing page, retrieved
    2026-11-27). Any other model or location is reported as unknown rather
    than guessed.
    """
    if model != PRICED_MODEL or location != PRICED_LOCATION:
        return CostEstimate(
            amount=None,
            label="unknown",
            note=(
                f"no list price is recorded for model {model!r} at location "
                f"{location!r} in this repository; the estimate is left unknown "
                "instead of guessed"
            ),
        )
    amount = (
        prompt_tokens * INPUT_PRICE_PER_MILLION
        + output_tokens * OUTPUT_PRICE_PER_MILLION
    ) / 1_000_000
    return CostEstimate(
        amount=amount,
        label=f"US${amount:.4f}",
        note=(
            "Standard PayGo Global list price for Gemini 4 Hydrogen: input "
            "US$1.50 / 1M tokens, output (response and reasoning) "
            "US$7.50 / 1M tokens (Model Garden pricing page, retrieved "
            "2026-11-27)"
        ),
    )


def estimate_prompt_tokens(prompt: str) -> int:
    """A pre-call input-token estimate: one token per four characters, rounded up.

    This is only used for the worst-case cost line printed before usage is
    known. It is not a live tokenizer call.
    """
    if not prompt:
        return 0
    return (len(prompt) + PROMPT_CHARS_PER_TOKEN - 1) // PROMPT_CHARS_PER_TOKEN


def sdk_http_options(config: LiveVertexConfig) -> dict[str, object]:
    """Keyword arguments for ``google.genai.types.HttpOptions``.

    ``timeout`` is in milliseconds, as required by the official SDK.
    ``retry_options.attempts`` is 1 (no retries) so the timeout and the
    token cap are not multiplied by the SDK's default of five attempts.
    """
    return {
        "timeout": int(config.timeout_seconds) * 1000,
        "retry_options": {"attempts": 1},
    }


def sdk_generate_config(config: LiveVertexConfig) -> dict[str, object]:
    """Keyword arguments for ``google.genai.types.GenerateContentConfig``.

    Both the output-token cap and the request timeout are included so a
    test can assert the cap wiring without importing the optional SDK.
    """
    return {
        "max_output_tokens": int(config.max_output_tokens),
        "http_options": sdk_http_options(config),
    }


def finish_reason_name(response: object) -> str | None:
    """Normalize a google-genai finish reason to a bare uppercase name."""
    candidates = getattr(response, "candidates", None) or ()
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    if reason is None:
        return None
    name = getattr(reason, "name", None) or getattr(reason, "value", None) or str(reason)
    text = str(name).replace("FinishReason.", "").replace("FINISH_REASON_", "")
    text = text.split(".")[-1].strip().upper()
    return text or None


def is_truncated_finish(reason: str | None) -> bool:
    """True when the model stopped because ``max_output_tokens`` was hit."""
    if not reason:
        return False
    return "MAX_TOKENS" in reason.upper().replace("-", "_")


def is_timeout_error(exc: BaseException) -> bool:
    """True when an SDK or HTTP exception is a request timeout."""
    names = [type(exc).__name__, *[base.__name__ for base in type(exc).mro()]]
    if any("timeout" in name.lower() for name in names):
        return True
    text = str(exc).lower()
    return "timed out" in text or "deadline exceeded" in text


def repo_root() -> Path:
    """The repository root (two parents above this package)."""
    return Path(__file__).resolve().parents[2]


def default_output_path() -> Path:
    """The gitignored default file for the generated chapter text."""
    return repo_root() / DEFAULT_OUTPUT_DIRNAME / DEFAULT_OUTPUT_FILENAME


def resolve_output_path(
    override: str | None,
    *,
    case_id: str = "case-a001",
    section_id: str = DEFAULT_SECTION_ID,
) -> Path:
    """Resolve the chapter output path from an override or the default."""
    if override and override.strip():
        raw = override.strip()
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if raw.endswith(("/", "\\")) or path.is_dir():
            path = path / f"{case_id}-{section_id}.txt"
        return path.resolve()
    return default_output_path()


def output_would_be_tracked(path: Path, repo: Path | None = None) -> bool:
    """True when ``path`` is inside the repo and is not gitignored."""
    repo = (repo or repo_root()).resolve()
    try:
        path.resolve().relative_to(repo)
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path.resolve())],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    relative = path.resolve().relative_to(repo).as_posix()
    return not relative.startswith(
        ("local-data/", "tmp/", "logs/", ".scratch/", ".cache/", "private/")
    )


def write_chapter_output(
    path: Path,
    text: str,
    *,
    repo: Path | None = None,
) -> Path:
    """Write the chapter text and return the absolute path.

    Refuses a path that would be tracked by git, so the file cannot land
    in the repository.
    """
    path = Path(path)
    if output_would_be_tracked(path, repo):
        raise LiveConfigError(
            f"refusing to write {path}: the path is inside the repository "
            "and is not gitignored"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def live_generate(config: LiveVertexConfig, prompt: str) -> LiveResponse:
    """Call Gemini on Vertex AI with Application Default Credentials.

    This is the only place the SDK is imported, so the optional ``live``
    extra is not needed to import this module or to run the test suite.
    The official getting-started guide also sets
    ``GOOGLE_GENAI_USE_ENTERPRISE`` for Agent Platform; it is applied
    for this call only and then restored. The output-token cap and the
    request timeout from ``config`` are always passed to the call. A
    timeout becomes a ``LiveResponse`` with ``timed_out=True`` so the
    caller can still run the guard and citation checks.
    """
    check_live_gate(config)
    from google import genai
    from google.genai import types

    generate_kwargs = sdk_generate_config(config)
    http_kwargs = sdk_http_options(config)
    http_options = types.HttpOptions(
        timeout=http_kwargs["timeout"],
        retry_options=types.HttpRetryOptions(**http_kwargs["retry_options"]),
    )
    previous = os.environ.get("GOOGLE_GENAI_USE_ENTERPRISE")
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "True"
    try:
        client = genai.Client(
            vertexai=True,
            project=config.project,
            location=config.location,
            http_options=http_options,
        )
        try:
            response = client.models.generate_content(
                model=config.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=generate_kwargs["max_output_tokens"],
                    http_options=http_options,
                ),
            )
        except Exception as exc:
            if not is_timeout_error(exc):
                raise
            return LiveResponse(text="", timed_out=True)
    finally:
        if previous is None:
            os.environ.pop("GOOGLE_GENAI_USE_ENTERPRISE", None)
        else:
            os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = previous
    return response_from_sdk(response)


def response_from_sdk(response: object) -> LiveResponse:
    """Normalize a google-genai response into :class:`LiveResponse`."""
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    candidates = int(getattr(usage, "candidates_token_count", 0) or 0)
    thoughts = int(getattr(usage, "thoughts_token_count", 0) or 0)
    output_tokens = candidates + thoughts
    total = int(getattr(usage, "total_token_count", 0) or 0)
    if not total:
        total = prompt_tokens + output_tokens
    text = getattr(response, "text", "") or ""
    reason = finish_reason_name(response)
    return LiveResponse(
        text=text,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        truncated=is_truncated_finish(reason),
        finish_reason=reason,
    )


def run_live_chapter(
    *,
    config: LiveVertexConfig,
    fixture_dir: Path,
    generate: GenerateCallable,
    workdir: Path | None = None,
    instructions: str = DEFAULT_INSTRUCTIONS,
    template_id: str = DEFAULT_TEMPLATE_ID,
    section_id: str = DEFAULT_SECTION_ID,
    output_path: Path | None = None,
) -> LiveChapterResult:
    """Gate, build the History prompt, generate once, then check the output."""
    check_live_gate(config)
    case_id = check_fixture_case(fixture_dir)

    template = load_template(template_id)
    section = next(
        (item for item in template.sections if item.id == section_id), None
    )
    if section is None:
        raise LiveCaseRefused(
            f"template {template_id!r} has no section {section_id!r}"
        )
    clinician_authored = is_clinician_authored_section(section)

    owned: tempfile.TemporaryDirectory[str] | None = None
    if workdir is not None:
        base = Path(workdir)
    else:
        owned = tempfile.TemporaryDirectory(prefix="psychtool-live-")
        base = Path(owned.name)
    try:
        workspace = prepare_workspace(Path(fixture_dir), base / "workspace")

        materials = list_materials(workspace)
        rows = extract_evidence(workspace, case_id)
        claim_ids = build_claims(workspace, materials)
        if not claim_ids:
            raise LiveCaseRefused(
                f"{fixture_dir} carries no evidence-backed statements to write from"
            )

        prompt, _source_refs = build_section_request_input(
            workspace,
            template_id=template_id,
            template_version=template.version,
            section_id=section_id,
            claim_ids=claim_ids,
            instructions=instructions,
        )

        try:
            response = generate(config, prompt)
        except Exception as exc:
            if not is_timeout_error(exc):
                raise
            response = LiveResponse(text="", timed_out=True)

        dest = output_path or resolve_output_path(
            config.output_override, case_id=case_id, section_id=section_id
        )
        written = write_chapter_output(dest, response.text)

        texts = uploaded_texts(workspace)
        evidence = sentence_evidence(rows)
        check = citecheck_text(
            section_id=section_id,
            text=response.text,
            evidence=evidence,
            uploaded_texts=texts,
            clinician_authored=clinician_authored,
            title=section.title,
        )
        wording_reason = check_draft_text(
            section_id,
            response.text,
            texts,
            clinician_authored=clinician_authored,
            title=section.title,
        )
        if check.blocked:
            guard_reason = check.detail or wording_reason or "citation check blocked"
        else:
            guard_reason = wording_reason
        cited = sum(1 for sentence in check.sentences if sentence.evidence_ids)
        total = len(check.sentences)
        estimated_prompt = estimate_prompt_tokens(prompt)
        return LiveChapterResult(
            case_id=case_id,
            section_id=section_id,
            project=config.project,
            location=config.location,
            model=config.model,
            text=response.text,
            total_sentences=total,
            cited_sentences=cited,
            uncited_sentences=total - cited,
            guard_blocked=guard_reason is not None,
            guard_reason=guard_reason,
            prompt_tokens=response.prompt_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            cost=estimate_cost(
                model=config.model,
                location=config.location,
                prompt_tokens=response.prompt_tokens,
                output_tokens=response.output_tokens,
            ),
            cost_worst_case=estimate_cost(
                model=config.model,
                location=config.location,
                prompt_tokens=estimated_prompt,
                output_tokens=config.max_output_tokens,
            ),
            estimated_prompt_tokens=estimated_prompt,
            max_output_tokens=config.max_output_tokens,
            timeout_seconds=config.timeout_seconds,
            truncated=response.truncated,
            timed_out=response.timed_out,
            finish_reason=response.finish_reason,
            output_path=str(written),
        )
    finally:
        if owned is not None:
            owned.cleanup()


def format_summary(result: LiveChapterResult) -> str:
    """A short pass/fail summary of one chapter run."""
    if result.guard_blocked:
        guard = f"FAIL ({result.guard_reason})"
    else:
        guard = "PASS (no diagnostic or un-uploaded wording)"
    worst = result.cost_worst_case
    worst_note = (
        f"input ~{result.estimated_prompt_tokens} tokens at "
        f"{PROMPT_CHARS_PER_TOKEN} chars/token, output at cap "
        f"{result.max_output_tokens}; {worst.note}"
    )
    result_line = f"RESULT: {result.status}"
    if result.fail_reasons:
        result_line = f"RESULT: FAIL ({'; '.join(result.fail_reasons)})"
    lines = [
        f"case: {result.case_id}   section: {result.section_id}",
        (
            f"model: {result.model}   location: {result.location}   "
            f"project: {result.project}"
        ),
        (
            f"cap: max_output_tokens={result.max_output_tokens}   "
            f"timeout={result.timeout_seconds}s"
        ),
        (
            f"sentences: {result.total_sentences} "
            f"(cited {result.cited_sentences}, uncited {result.uncited_sentences})"
        ),
        f"guard: {guard}",
        (
            f"tokens: prompt {result.prompt_tokens}, output {result.output_tokens}, "
            f"total {result.total_tokens}"
        ),
        f"cost worst-case at cap: {worst.label} ({worst_note})",
        f"cost actual: {result.cost.label} ({result.cost.note})",
        f"output: {result.output_path or '(not written)'}",
        result_line,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point for the manual live chapter run."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="live-vertex-chapter",
        description=(
            "Generate one History chapter from the synthetic fixture with Gemini "
            "on Vertex AI. Requires PSYCHTOOL_LIVE_VERTEX=1 and --opt-in."
        ),
    )
    parser.add_argument(
        "--opt-in",
        action="store_true",
        help="explicit opt-in; required together with PSYCHTOOL_LIVE_VERTEX=1",
    )
    parser.add_argument("--project", default=None, help="Google Cloud project id")
    parser.add_argument("--location", default=None, help="Vertex AI location")
    parser.add_argument("--model", default=None, help="Gemini model id")
    parser.add_argument(
        "--fixture",
        default=None,
        help="synthetic fixture case directory (default: fixtures/case_a001)",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="scratch directory for the copied workspace",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "file (or directory) for the generated chapter text; default: "
            "local-data/live-vertex/case-a001-history.txt"
        ),
    )
    parser.add_argument(
        "--max-output-tokens",
        default=None,
        help=f"output-token cap sent to the model (default: {DEFAULT_MAX_OUTPUT_TOKENS})",
    )
    parser.add_argument(
        "--timeout-seconds",
        default=None,
        help=f"request timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--instructions",
        default=DEFAULT_INSTRUCTIONS,
        help="writing instructions handed to the model",
    )
    args = parser.parse_args(argv)

    try:
        config = parse_live_config(
            project=args.project,
            location=args.location,
            model=args.model,
            opt_in=args.opt_in,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout_seconds,
            output=args.output,
        )
    except LiveChapterError as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return EXIT_REFUSED
    fixture_dir = Path(args.fixture) if args.fixture else default_fixture_dir()
    try:
        result = run_live_chapter(
            config=config,
            fixture_dir=fixture_dir,
            generate=live_generate,
            workdir=Path(args.workdir) if args.workdir else None,
            instructions=args.instructions,
        )
    except LiveChapterError as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return EXIT_REFUSED
    sys.stdout.write(format_summary(result) + "\n")
    return EXIT_OK if result.status == "PASS" else EXIT_GUARD_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
