"""typer command surface (ADR 0006): init / import / claims / draft / review / export."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from psychtool.config import Config, load_config
from psychtool.gateway.select import select_transport
from psychtool.gateway.orchestrator import (
    ApprovalChoice,
    EgressApprovalRequired,
    EgressOrchestrator,
    HumanApproval,
    SyntheticApproval,
)
from psychtool.core.protected import ProtectedContentError
from psychtool.core.workspace import (
    get_known_names,
    import_material,
    init_workspace,
    set_known_names,
)
from psychtool.core.claims import list_claims, add_claim, mark_status
from psychtool.core.draft import BudgetExceeded, generate_draft
from psychtool.core.review import review_summary
from psychtool.core.export import preview_export, export_draft
from psychtool.core.eval import load_fixture, run_eval
from psychtool.core.judge import judge_draft
from psychtool.core.egress import EgressRequest
from psychtool.banner.banner import render_banner

app = typer.Typer()


def _show_prepared_request(request: EgressRequest) -> None:
    typer.echo(f"request_id: {request.request_id}")
    typer.echo(f"status: {request.status}")
    typer.echo(f"hash: {request.content_hash}")
    typer.echo("redacted preview:")
    typer.echo(request.envelope.messages[0]["content"])


def _confirm_human_request(request: EgressRequest) -> bool:
    return typer.confirm("Send this exact redacted request?", default=False, abort=True)


def _approval_choice(
    config: Config,
    *,
    reviewer: str | None,
    synthetic_auto: bool,
    approval_reason: str | None,
) -> ApprovalChoice:
    if reviewer is not None and (synthetic_auto or approval_reason is not None):
        raise typer.BadParameter("real and synthetic approval options cannot be mixed")

    if config.data_tier == "real":
        if synthetic_auto or approval_reason is not None:
            raise typer.BadParameter("synthetic approval options cannot be used with real data")
        if reviewer is None or not reviewer.strip():
            return None
        return HumanApproval(reviewer=reviewer, confirm=_confirm_human_request)

    if reviewer is not None:
        raise typer.BadParameter("--reviewer cannot be used with synthetic data")
    if not synthetic_auto or approval_reason is None or not approval_reason.strip():
        return None
    return SyntheticApproval(reason=approval_reason)


def _cli_transport(config: Config, envelope: dict) -> str:
    """Dispatch to the configured transport. Tests may monkeypatch this hook."""
    return select_transport(config)(config, envelope)


def _runner(
    config: Config,
    approval: ApprovalChoice,
) -> EgressOrchestrator:
    return EgressOrchestrator(
        config=config,
        approval=approval,
        transport=_cli_transport,
        on_prepared=_show_prepared_request,
    )


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    no_dash: bool = typer.Option(False, "--no-dash", help="只显示横幅，不进入 dash"),
):
    if ctx.invoked_subcommand is not None:
        return
    cfg = load_config()
    use_color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    sys.stdout.write(render_banner(cfg, use_color=use_color))
    if not no_dash:
        sys.stdout.write("\n打开仪表盘：psychtool dash <工作区路径>\n")


@app.command()
def init(path: str, case_id: str = typer.Option(..., "--case-id")):
    """Create a workspace directory marked as synthetic training data."""
    init_workspace(Path(path), case_id=case_id)
    typer.echo(f"initialized workspace at {path}")


@app.command("import")
def import_material_cmd(
    path: str,
    material_id: str = typer.Option(..., "--material-id"),
    title: str = typer.Option(..., "--title"),
    provider: str = typer.Option(..., "--provider"),
    date: str = typer.Option(..., "--date"),
    file: str = typer.Option(..., "--file"),
):
    """Import a text material into the workspace (versioned)."""
    text = Path(file).read_text(encoding="utf-8")
    blocked: list[int] = []
    try:
        mat = import_material(
            Path(path), material_id=material_id, title=title, provider=provider,
            date=date, text=text, blocked_out=blocked,
        )
    except ProtectedContentError as exc:
        # Fixed message only; never quote the file name or its text (ADR 0013).
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"imported {material_id} v{mat.version}")
    if blocked and blocked[0]:
        count = blocked[0]
        typer.echo(
            f"held back {count} paragraph(s): they appear to contain test "
            "items, norms or scoring rules; not stored, never sent"
        )


@app.command("import-json")
def import_json_cmd(
    workspace_dir: str,
    db: str = typer.Option(None, "--db"),
):
    """Import an ADR 0005 JSON workspace directory into the SQLite store.

    The whole workspace loads as one transaction: on any error nothing is
    written. Refuses to import over an existing case id. Without ``--db`` the
    database resolves exactly like the server: ``PSYCHTOOL_DB_PATH`` first,
    else ``local-data/psychtool.db``.
    """
    from psychtool.store.sqlite_store import SqliteStore, default_db_path

    db_path = Path(db) if db else default_db_path()
    try:
        case_id = SqliteStore(db_path).import_workspace(Path(workspace_dir))
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    except Exception as exc:
        from psychtool.store.sqlite_store import CaseExistsError

        if isinstance(exc, CaseExistsError):
            typer.echo(f"case already exists: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        raise
    typer.echo(f"imported case {case_id} into {db_path}")


@app.command("live-vertex-chapter")
def live_vertex_chapter_cmd(
    opt_in: bool = typer.Option(
        False,
        "--opt-in",
        help="Explicit opt-in; required together with PSYCHTOOL_LIVE_VERTEX=1",
    ),
    project: str = typer.Option(None, "--project", help="Google Cloud project id"),
    location: str = typer.Option(None, "--location", help="Vertex AI location"),
    model: str = typer.Option(None, "--model", help="Gemini model id"),
    fixture: str = typer.Option(
        None, "--fixture", help="Synthetic fixture case directory"
    ),
    output: str = typer.Option(
        None,
        "--output",
        help="File or directory for the generated chapter text",
    ),
    max_output_tokens: int = typer.Option(
        None,
        "--max-output-tokens",
        help="Output-token cap sent to the model (default: 8192)",
    ),
    timeout_seconds: int = typer.Option(
        None,
        "--timeout-seconds",
        help="Request timeout in seconds (default: 120)",
    ),
):
    """Generate one History chapter from the synthetic fixture (live, opt-in).

    Needs PSYCHTOOL_LIVE_VERTEX=1 in the environment and --opt-in on the
    command line. Any ``real`` profile or data tier is refused even then
    (ADR 0024). The SDK comes from the optional ``live`` extra.
    """
    from psychtool.live.vertex_chapter import (
        LiveChapterError,
        default_fixture_dir,
        format_summary,
        live_generate,
        parse_live_config,
        run_live_chapter,
    )

    try:
        config = parse_live_config(
            project=project,
            location=location,
            model=model,
            opt_in=opt_in,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            output=output,
        )
    except LiveChapterError as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(code=2) from None
    fixture_dir = Path(fixture) if fixture else default_fixture_dir()
    try:
        result = run_live_chapter(
            config=config,
            fixture_dir=fixture_dir,
            generate=live_generate,
        )
    except LiveChapterError as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(format_summary(result))
    if result.status != "PASS":
        raise typer.Exit(code=1)


claims_app = typer.Typer()
app.add_typer(claims_app, name="claims")


@claims_app.command("list")
def claims_list(path: str):
    """List candidate claims."""
    for c in list_claims(Path(path)):
        typer.echo(f"{c.id}\t{c.verification_status}\t{c.text}")


@claims_app.command("add")
def claims_add(
    path: str,
    id: str = typer.Option(..., "--id"),
    doc: str = typer.Option(..., "--doc"),
    ver: int = typer.Option(..., "--ver"),
    passage: str = typer.Option(..., "--passage"),
    role: str = typer.Option(..., "--role"),
    setting: str = typer.Option(..., "--setting"),
    record: str = typer.Option(..., "--record"),
    category: str = typer.Option(..., "--category"),
    topic: str = typer.Option(..., "--topic"),
    text: str = typer.Option(..., "--text"),
):
    """Add a candidate claim."""
    add_claim(
        Path(path),
        claim_id=id,
        source_document_id=doc,
        source_version=ver,
        source_passage_id=passage,
        provider_role=role,
        observation_setting=setting,
        record_time=record,
        category=category,
        topic=topic,
        text=text,
    )
    typer.echo(f"added claim {id}")


@claims_app.command("status")
def claims_status(path: str, id: str, status: str):
    """Set a claim's verification status."""
    mark_status(Path(path), id, status)
    typer.echo(f"claim {id} -> {status}")


fields_app = typer.Typer()
app.add_typer(fields_app, name="fields")


@fields_app.command("set")
def fields_set(
    path: str,
    name: list[str] = typer.Option(..., "--name", help="Identifying name; repeatable"),
):
    """Persist identifying names (client/evaluator) used for redaction."""
    saved = set_known_names(Path(path), name)
    typer.echo(f"saved {len(saved)} known names for redaction")


@fields_app.command("list")
def fields_list(path: str):
    """List the identifying names persisted for redaction."""
    for n in get_known_names(Path(path)):
        typer.echo(n)


@app.command()
def draft(
    path: str,
    claim_ids: str = typer.Option(..., "--claim-ids"),
    instructions: str = typer.Option(..., "--instructions"),
    draft_id: str = typer.Option("d1", "--draft-id"),
    max_steps: int = typer.Option(1, "--max-steps"),
    max_cost: float = typer.Option(
        None,
        "--max-cost",
        help="Cost limit; currently unsupported and fails closed when provided",
    ),
    reviewer: str = typer.Option(None, "--reviewer"),
    synthetic_auto: bool = typer.Option(False, "--synthetic-auto"),
    approval_reason: str = typer.Option(None, "--approval-reason"),
):
    """Generate a draft through a persisted, explicitly approved request."""
    ids = [s.strip() for s in claim_ids.split(",") if s.strip()]
    cfg = load_config()
    approval = _approval_choice(
        cfg,
        reviewer=reviewer,
        synthetic_auto=synthetic_auto,
        approval_reason=approval_reason,
    )
    try:
        result = generate_draft(
            Path(path),
            draft_id=draft_id,
            claim_ids=ids,
            instructions=instructions,
            runner=_runner(cfg, approval),
            max_steps=max_steps,
            max_cost=max_cost,
        )
    except EgressApprovalRequired:
        raise typer.Exit(code=1) from None
    except BudgetExceeded as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(result.text)


@app.command()
def review(path: str):
    """Summarise conflicts, gaps, stale claims and stale drafts."""
    typer.echo(json.dumps(review_summary(Path(path)), ensure_ascii=False, indent=2))


@app.command()
def export(path: str, draft_id: str = typer.Option(..., "--draft-id"), out: str = typer.Option(..., "--out")):
    """Preview then write a draft and its source index to a target path."""
    preview = preview_export(Path(path), draft_id)
    typer.echo("preview:")
    typer.echo(preview["text"])
    typer.echo(f"sources: {len(preview['sources'])}")
    export_draft(Path(path), draft_id, Path(out))
    typer.echo(f"exported to {out}")


@app.command("eval")
def eval_cmd(
    fixture_path: str = typer.Option(..., "--fixture"),
    out: str = typer.Option(None, "--out"),
    synthetic_auto: bool = typer.Option(False, "--synthetic-auto"),
    approval_reason: str = typer.Option(None, "--approval-reason"),
):
    """Run single vs staged generation on an explicitly approved synthetic fixture."""
    import tempfile

    cfg = load_config()
    if cfg.data_tier != "synthetic":
        raise typer.BadParameter("eval only accepts synthetic fixture data")
    if not synthetic_auto or approval_reason is None or not approval_reason.strip():
        raise typer.BadParameter(
            "eval requires --synthetic-auto and a nonempty --approval-reason"
        )
    approval = SyntheticApproval(reason=approval_reason)
    fx = load_fixture(Path(fixture_path))
    root = Path(tempfile.mkdtemp(prefix="psychtool-eval-"))
    report = run_eval(fx, runner=_runner(cfg, approval), root=root)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        typer.echo(f"report written to {out}")
    else:
        typer.echo(text)


@app.command("judge")
def judge_cmd(
    path: str,
    draft_id: str = typer.Option(..., "--draft-id"),
    reviewer: str = typer.Option(None, "--reviewer"),
    synthetic_auto: bool = typer.Option(False, "--synthetic-auto"),
    approval_reason: str = typer.Option(None, "--approval-reason"),
):
    """Judge each claim through a separately approved model request."""
    cfg = load_config()
    approval = _approval_choice(
        cfg,
        reviewer=reviewer,
        synthetic_auto=synthetic_auto,
        approval_reason=approval_reason,
    )
    judge_config = cfg.model_copy(update={"model": cfg.judge_model})
    try:
        archive = judge_draft(
            Path(path),
            draft_id,
            runner=_runner(judge_config, approval),
        )
    except EgressApprovalRequired:
        raise typer.Exit(code=1) from None
    typer.echo(json.dumps(archive, ensure_ascii=False, indent=2))


@app.command("dash")
def dash_cmd(path: str):
    """Open the interactive dashboard for a workspace."""
    from psychtool.tui.app import DashApp

    DashApp(path).run()


if __name__ == "__main__":
    app()
