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
  text is never rewritten.

The google-genai SDK is an optional extra (``live``) and is imported only
inside :func:`live_generate`, so the default test run never needs it and no
test in this repository makes a live call.
"""

from __future__ import annotations

import json
import os
import shutil
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

DEFAULT_PROJECT = "fb-ailogic26vrt-3252"
DEFAULT_LOCATION = "global"
DEFAULT_MODEL = "gemini-4-hydrogen"
DEFAULT_TEMPLATE_ID = "intake-report"
DEFAULT_SECTION_ID = "history"

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

    @property
    def status(self) -> str:
        """``PASS`` when the wording guard is clean, ``FAIL`` when it blocked."""
        return "FAIL" if self.guard_blocked else "PASS"


GenerateCallable = Callable[[LiveVertexConfig, str], LiveResponse]


def _env_flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_live_config(
    *,
    project: str | None = None,
    location: str | None = None,
    model: str | None = None,
    opt_in: bool = False,
    environ: Mapping[str, str] | None = None,
) -> LiveVertexConfig:
    """Resolve the live configuration from flags and environment variables.

    Precedence: command-line flag, then environment variable, then default.
    The project defaults to ``fb-ailogic26vrt-3252``, the location to
    ``global`` and the model to ``gemini-4-hydrogen``. The model environment
    variable is ``PSYCHTOOL_LIVE_VERTEX_MODEL``; ``PSYCHTOOL_MODEL`` is used
    as a fallback so the live path follows the same model setting as the
    rest of the product.
    """
    env = os.environ if environ is None else environ
    resolved_project = (project or env.get(ENV_VERTEX_PROJECT) or "").strip()
    resolved_location = (location or env.get(ENV_VERTEX_LOCATION) or "").strip()
    resolved_model = (
        model or env.get(ENV_LIVE_VERTEX_MODEL) or env.get(ENV_MODEL) or ""
    ).strip()
    return LiveVertexConfig(
        project=resolved_project or DEFAULT_PROJECT,
        location=resolved_location or DEFAULT_LOCATION,
        model=resolved_model or DEFAULT_MODEL,
        env_opt_in=_env_flag(env.get(ENV_LIVE_VERTEX)),
        cli_opt_in=bool(opt_in),
        profile=(env.get(ENV_PROFILE) or DEFAULT_PROFILE).strip().lower(),
        data_tier=(env.get(ENV_DATA_TIER) or DEFAULT_DATA_TIER).strip().lower(),
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


def live_generate(config: LiveVertexConfig, prompt: str) -> LiveResponse:
    """Call Gemini on Vertex AI with Application Default Credentials.

    This is the only place the SDK is imported, so the optional ``live``
    extra is not needed to import this module or to run the test suite.
    The official getting-started guide also sets
    ``GOOGLE_GENAI_USE_ENTERPRISE`` for Agent Platform; it is applied
    for this call only and then restored.
    """
    from google import genai

    previous = os.environ.get("GOOGLE_GENAI_USE_ENTERPRISE")
    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "True"
    try:
        client = genai.Client(
            vertexai=True,
            project=config.project,
            location=config.location,
        )
        response = client.models.generate_content(model=config.model, contents=prompt)
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
    return LiveResponse(
        text=text,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
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

    base = (
        Path(workdir)
        if workdir is not None
        else Path(tempfile.mkdtemp(prefix="psychtool-live-"))
    )
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

    response = generate(config, prompt)

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
    )


def format_summary(result: LiveChapterResult) -> str:
    """A short pass/fail summary of one chapter run."""
    if result.guard_blocked:
        guard = f"FAIL ({result.guard_reason})"
    else:
        guard = "PASS (no diagnostic or un-uploaded wording)"
    lines = [
        f"case: {result.case_id}   section: {result.section_id}",
        (
            f"model: {result.model}   location: {result.location}   "
            f"project: {result.project}"
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
        f"cost: {result.cost.label} ({result.cost.note})",
        f"RESULT: {result.status}",
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
        "--instructions",
        default=DEFAULT_INSTRUCTIONS,
        help="writing instructions handed to the model",
    )
    args = parser.parse_args(argv)

    config = parse_live_config(
        project=args.project,
        location=args.location,
        model=args.model,
        opt_in=args.opt_in,
    )
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
    return EXIT_OK if not result.guard_blocked else EXIT_GUARD_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
