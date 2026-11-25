"""FastAPI application factory and routes.

Serves the JSON API under ``/api`` and, when a production build exists in
``web/dist``, serves the React SPA with client-side routing fallback. During
development the SPA is served by Vite (see ``web/vite.config.ts``), which
proxies ``/api`` to this server.

Persistence (ADR 0010): all case data lives in one SQLite database
(``PSYCHTOOL_DB_PATH``, default ``local-data/psychtool.db``). Every request
opens one ``CaseStore`` bound to the URL ``case_id``; the store refuses ids
that do not pass the shared case-id pattern, and all SQL is parameterized by
``case_id`` so one case can never read or mutate another case's rows.

Security (ADR 0011): every request passes the loopback Host check; every
``/api/*`` call except ``GET /api/health`` needs the per-start session token;
every response carries strict security headers; the SPA shell is served with
the token injected as a meta tag and ``Cache-Control: no-store``. Error
responses use fixed generic strings so user text can never leak through a
4xx/5xx body.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError

from psychtool import __version__
from psychtool.core.intake_claims import ClaimSuggestion, accept_suggestion, suggest_claims
from psychtool.core.ingest import (
    MAX_UPLOAD_BYTES,
    ServerUploadError,
    import_upload,
    parse_server_upload,
)
from psychtool.core.egress import (
    EgressApprovalError,
    EgressBlockedError,
    EgressPurpose,
    EgressRequest,
    EgressStaleError,
    EgressStateError,
    approve_human,
    approve_synthetic,
    get_egress_request,
    prepare_egress_request,
)
from psychtool.core.report_templates import list_templates, load_template, manifest_as_dict
from psychtool.core.sections import (
    SectionStatus,
    build_section_request_input,
    save_section,
    section_states,
)
from psychtool.config import Config, load_config
from psychtool.gateway.client import (
    EgressOutputBlockedError,
    NetworkForbiddenError,
    send_approved,
)
from psychtool.gateway.fake import fake_transport
from psychtool.gateway.http import http_transport
from psychtool.server.security import (
    LocalSecurityMiddleware,
    SecurityHeadersASGIMiddleware,
    inject_session_meta,
    resolve_session_token,
)
from psychtool.store.sqlite_store import (
    CaseExistsError,
    CaseStore,
    SqliteStore,
    UnknownCaseError,
    default_db_path,
)

logger = logging.getLogger("psychtool")

# Project root is two levels up from psychtool/server/app.py.
_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


class SectionPayload(BaseModel):
    template_id: str
    template_version: int
    text: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    status: SectionStatus = "draft"
    reviewer: str | None = None


class NamesPayload(BaseModel):
    names: list[str] = Field(default_factory=list)


class PrepareEgressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    template_version: int
    section_id: str
    claim_ids: list[str] = Field(default_factory=list)
    instructions: str = ""
    purpose: EgressPurpose


class ApproveEgressPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_hash: str
    reviewer: str | None = None
    synthetic_auto_reason: str | None = None


_CASE_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


class CreateCasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=_CASE_ID_RE)


class PasteMaterialPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str
    title: str
    provider: str
    date: str
    text: str
    synthetic_confirmed: bool = False


def _egress_response(request: EgressRequest) -> dict:
    """Return the persisted review surface without runtime-only configuration."""
    return {
        "request_id": request.request_id,
        "workspace_id": request.workspace_id,
        "purpose": request.purpose,
        "data_tier": request.data_tier,
        "provider_base_url": request.provider_base_url,
        "model": request.envelope.model,
        "preview": request.envelope.messages[0]["content"],
        "source_refs": [ref.model_dump() for ref in request.source_refs],
        "identifier_categories": request.identifier_categories,
        "content_hash": request.content_hash,
        "status": request.status,
        "approval_mode": request.approval_mode,
        "reviewer": request.reviewer,
        "approval_reason": request.approval_reason,
        "prepared_at": request.prepared_at,
        "approved_at": request.approved_at,
        "sent_at": request.sent_at,
        "requires_human_review": True,
    }


def _db_path() -> Path:
    return default_db_path()


def _select_transport(config: Config):
    """Pick the model transport from config; the offline fake is the default.

    ``http_transport`` is reachable only through the explicit
    ``PSYCHTOOL_TRANSPORT=http`` opt-in, so the default dev run, tests and the
    e2e never open a socket. Every existing gateway check (approval hash,
    send-once lock, data tier, output PII gate) runs before any transport.
    """
    if config.transport == "http":
        return http_transport
    return fake_transport


def _wrap_stack_with_security_headers(app: FastAPI) -> None:
    """Ensure the outermost middleware is SecurityHeadersASGIMiddleware.

    Starlette always puts ``ServerErrorMiddleware`` first (outside user
    middleware), and it sends its 500 response via the original ``send`` —
    so headers injected by any ``add_middleware`` middleware are missing from
    that response. Wrapping the built stack places header injection truly
    outermost, covering the fixed 500 as well as every normal response.
    """
    original_build = app.build_middleware_stack

    def build() -> object:
        return SecurityHeadersASGIMiddleware(original_build())

    app.build_middleware_stack = build  # type: ignore[method-assign]


def create_app(session_token: str | None = None) -> FastAPI:
    app = FastAPI(title="psychtool", version=__version__)
    token, token_source = resolve_session_token(session_token)
    app.state.session_token = token
    app.state.session_token_source = token_source
    # Never log the token value; the startup log names only its origin.
    logger.info("session token: %s (not shown)", token_source)
    store = SqliteStore(_db_path())
    app.state.store = store
    app.add_middleware(LocalSecurityMiddleware, session_token=token)
    # Wrap the *built* stack (outside Starlette's ServerErrorMiddleware) so
    # the fixed 500 it sends for an unhandled exception also carries the
    # PT-03 security headers (ADR 0012). ``add_middleware`` cannot do this:
    # user middleware always sits *inside* ServerErrorMiddleware, whose error
    # response is sent via the original ``send``.
    _wrap_stack_with_security_headers(app)

    def _case(case_id: str) -> CaseStore:
        """Bind one case; 400 for malformed ids, 404 for unknown ones."""
        try:
            return store.case(case_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid case id") from exc
        except UnknownCaseError as exc:
            raise HTTPException(status_code=404, detail="case not found") from exc

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request, exc) -> JSONResponse:
        _ = request, exc
        return JSONResponse(status_code=400, content={"detail": "invalid request"})

    @app.exception_handler(Exception)
    async def unhandled_error(request, exc) -> JSONResponse:
        """Catch-all (ADR 0012): fixed body, log the exception *type* only.

        ``str(exc)`` and tracebacks may quote request or material text, so
        only the class name is logged, exactly once, here. The response body
        is a fixed string; the security headers are attached by
        SecurityHeadersASGIMiddleware, which wraps the outermost stack.
        """
        _ = request
        logger.error("unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/templates")
    def templates() -> list[dict]:
        return [manifest_as_dict(template) for template in list_templates()]

    @app.get("/api/templates/{template_id}")
    def template(template_id: str) -> dict:
        try:
            return manifest_as_dict(load_template(template_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="template not found") from exc

    @app.get("/api/workspaces")
    def workspaces() -> list[dict]:
        return [{"case_id": case_id} for case_id in store.list_cases()]

    @app.post("/api/workspaces", status_code=201)
    def create_workspace(body: CreateCasePayload) -> dict:
        case_id = body.case_id
        try:
            store.create_case(case_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid case id") from exc
        except CaseExistsError as exc:
            raise HTTPException(status_code=409, detail="case already exists") from exc
        return {"case_id": case_id}

    @app.post("/api/workspaces/{case_id}/synthetic-confirmation")
    def confirm_synthetic(case_id: str) -> dict:
        """Record the R2-AC3 first-upload confirmation (idempotent, ADR 0012).

        The audit row is written only when the confirmation actually changes
        the case, so calling this twice appends exactly one
        ``case.confirm_synthetic`` row.
        """
        case = _case(case_id)
        case.confirm_synthetic()  # audit row written in the same transaction
        return {"case_id": case_id, "synthetic_confirmed": True}

    @app.get("/api/workspaces/{case_id}")
    def workspace(case_id: str) -> dict:
        case = _case(case_id)
        return {
            "case_id": case_id,
            "synthetic_confirmed": case.is_synthetic_confirmed(),
        }

    @app.get("/api/workspaces/{case_id}/materials")
    def materials(case_id: str) -> list[dict]:
        return [m.model_dump() for m in _case(case_id).list_materials()]

    @app.post("/api/workspaces/{case_id}/materials")
    async def upload_material(case_id: str, file: UploadFile = File(...),
                              material_id: str = Form(...), title: str = Form(...),
                              provider: str = Form(...), date: str = Form(...)) -> dict:
        case = _case(case_id)
        # R2-AC3: no upload before the per-case synthetic confirmation.
        if not case.is_synthetic_confirmed():
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "Confirm that this case uses only synthetic or "
                              "separately approved materials before uploading.",
                    "reason": "confirmation_required",
                },
            )
        # Everything is validated before the store is touched; the store
        # write itself (material + passages + audit row) is one transaction,
        # so a rejection can never leave a partial write behind.
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        try:
            text = parse_server_upload(file.filename or "", data)
        except ServerUploadError as exc:
            status = 413 if exc.reason == "too_large" else 400
            return JSONResponse(
                status_code=status,
                content={"detail": str(exc), "reason": exc.reason},
            )
        try:
            material, findings = import_upload(
                case, filename=file.filename or "", data=data,
                material_id=material_id, title=title, provider=provider, date=date,
            )
        except (UnicodeError, KeyError, ValueError) as exc:
            # Fixed detail: the exception message may quote the uploaded text.
            raise HTTPException(
                status_code=400, detail="material could not be imported"
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="import unavailable") from exc
        return {"material": material.model_dump(), "identifier_findings": findings,
                "requires_human_review": True}

    @app.post("/api/workspaces/{case_id}/materials/paste")
    def paste_material(case_id: str, body: PasteMaterialPayload) -> dict:
        case = _case(case_id)
        if not body.synthetic_confirmed:
            raise HTTPException(
                status_code=400,
                detail="pasted text must be confirmed as synthetic",
            )
        try:
            data = body.text.encode("utf-8")
            material, findings = import_upload(
                case, filename="pasted-synthetic-text.txt", data=data,
                material_id=body.material_id, title=body.title,
                provider=body.provider, date=body.date,
            )
        except (UnicodeError, KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="pasted material could not be accepted"
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="paste import unavailable") from exc
        # A confirmed paste is itself the R2-AC3 confirmation: recording it
        # here means the file form stops asking once any material was
        # confirmed as synthetic (ADR 0012). One audit row, set-once.
        case.confirm_synthetic()  # audit row written in the same transaction
        return {"material": material.model_dump(), "identifier_findings": findings,
                "requires_human_review": True}

    @app.get("/api/workspaces/{case_id}/claims")
    def claims(case_id: str) -> list[dict]:
        return [c.model_dump() for c in _case(case_id).list_claims()]

    @app.get("/api/workspaces/{case_id}/materials/{material_id}/suggestions")
    def claim_suggestions(case_id: str, material_id: str, provider_role: str) -> list[dict]:
        try:
            return [s.model_dump() for s in suggest_claims(
                _case(case_id), material_id, provider_role=provider_role
            )]
        except (KeyError, ValueError, ValidationError) as exc:
            # Fixed detail: validation errors may quote pasted source text.
            raise HTTPException(status_code=400, detail="invalid request") from exc

    @app.post("/api/workspaces/{case_id}/claims")
    def accept_claim(case_id: str, body: ClaimSuggestion) -> dict:
        case = _case(case_id)
        try:
            claim = accept_suggestion(case, body)
        except (KeyError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail="invalid claim") from exc
        # ``claim.accept`` is appended by the store in the same transaction
        # as the claim insert (ADR 0011).
        return claim.model_dump()

    @app.get("/api/workspaces/{case_id}/names")
    def names(case_id: str) -> dict:
        return {"names": list(_case(case_id).get_known_names())}

    @app.put("/api/workspaces/{case_id}/names")
    def put_names(case_id: str, body: NamesPayload) -> dict:
        return {"names": list(_case(case_id).set_known_names(body.names))}

    @app.get("/api/workspaces/{case_id}/sections")
    def sections(case_id: str, template_id: str) -> list[dict]:
        return section_states(_case(case_id), template_id)

    @app.put("/api/workspaces/{case_id}/sections/{section_id}")
    def put_section(case_id: str, section_id: str, body: SectionPayload) -> dict:
        try:
            draft = save_section(
                _case(case_id),
                template_id=body.template_id,
                template_version=body.template_version,
                section_id=section_id,
                text=body.text,
                claim_ids=body.claim_ids,
                status=body.status,
                reviewer=body.reviewer,
            )
        except (KeyError, ValueError) as exc:
            # Fixed detail: section errors may quote claim ids or text.
            raise HTTPException(status_code=400, detail="invalid section") from exc
        return draft.model_dump()

    @app.post("/api/workspaces/{case_id}/egress/prepare")
    def prepare_egress(case_id: str, body: PrepareEgressPayload) -> dict:
        try:
            case = _case(case_id)
            prompt, source_refs = build_section_request_input(
                case,
                template_id=body.template_id,
                template_version=body.template_version,
                section_id=body.section_id,
                claim_ids=body.claim_ids,
                instructions=body.instructions,
            )
            request = prepare_egress_request(
                case,
                prompt=prompt,
                purpose=body.purpose,
                config=load_config(),
                source_refs=source_refs,
            )
        except (EgressBlockedError, KeyError, ValueError, ValidationError, OSError) as exc:
            raise HTTPException(status_code=400, detail="invalid egress request") from exc
        # ``egress.prepare`` is appended by the store in the same transaction
        # as the request row (ADR 0011).
        return _egress_response(request)

    @app.get("/api/workspaces/{case_id}/egress/{request_id}")
    def get_egress(case_id: str, request_id: str) -> dict:
        try:
            request = get_egress_request(_case(case_id), request_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="egress request not found") from exc
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail="invalid egress request") from exc
        return _egress_response(request)

    @app.post("/api/workspaces/{case_id}/egress/{request_id}/approve")
    def approve_egress(
        case_id: str,
        request_id: str,
        body: ApproveEgressPayload,
    ) -> dict:
        if (body.reviewer is None) == (body.synthetic_auto_reason is None):
            raise HTTPException(
                status_code=400,
                detail="exactly one approval method is required",
            )
        case = _case(case_id)
        try:
            if body.reviewer is not None:
                request = approve_human(
                    case,
                    request_id,
                    reviewer=body.reviewer,
                    content_hash=body.content_hash,
                )
            else:
                request = approve_synthetic(
                    case,
                    request_id,
                    reason=body.synthetic_auto_reason or "",
                    content_hash=body.content_hash,
                )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="egress request not found") from exc
        except EgressApprovalError as exc:
            raise HTTPException(status_code=400, detail="egress approval rejected") from exc
        except EgressStateError as exc:
            raise HTTPException(status_code=409, detail="egress request state conflict") from exc
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail="invalid egress request") from exc
        # ``egress.approve`` is appended by the store in the same transaction
        # as the approval (ADR 0011).
        return _egress_response(request)

    @app.post("/api/workspaces/{case_id}/egress/{request_id}/send")
    def send_egress(case_id: str, request_id: str) -> dict:
        config = load_config()
        case = _case(case_id)
        # The store records the transport on the ``egress.send`` audit row it
        # appends in the same transaction as the ``sent`` status change.
        case.audit_destination = config.transport
        try:
            text = send_approved(
                case,
                request_id,
                config=config,
                transport=_select_transport(config),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="egress request not found") from exc
        except NetworkForbiddenError as exc:
            raise HTTPException(status_code=403, detail="model network access forbidden") from exc
        except EgressOutputBlockedError as exc:
            # The request is already ``sent`` at this point (send-once), but
            # the blocked output is a security-relevant event worth auditing.
            try:
                blocked = get_egress_request(case, request_id)
                case.append_audit(
                    case_id=case_id,
                    action="egress.output_blocked",
                    object_type="egress_request",
                    object_id=request_id,
                    content_hash=blocked.content_hash,
                )
            except Exception:  # pragma: no cover - audit must not mask the 422
                # Fixed string only: no exception text may reach the logs.
                logger.error("could not audit blocked model output")
            raise HTTPException(status_code=422, detail="model output blocked") from exc
        except (EgressStateError, EgressStaleError) as exc:
            raise HTTPException(status_code=409, detail="egress request state conflict") from exc
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail="invalid egress request") from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=502, detail="model request failed") from exc
        # ``egress.send`` was appended atomically with the ``sent`` status;
        # a failed audit write rolls the state change back instead, so the
        # request can never be ``sent`` without its audit row.
        return {"request_id": request_id, "status": "sent", "text": text}

    @app.post("/api/workspaces/{case_id}/sections/{section_id}/generate")
    def generate(case_id: str, section_id: str) -> None:
        # Resolve the case first so unknown ids still surface as 404.
        _ = section_id, _case(case_id)
        raise HTTPException(
            status_code=410,
            detail="Direct generation is gone; use egress prepare, approve, and send.",
        )

    _mount_spa(app, token)
    return app


def _mount_spa(app: FastAPI, session_token: str) -> None:
    """Serve the built SPA if ``web/dist`` exists, with SPA fallback.

    The index shell is rendered per request with the session-token meta tag
    injected and ``Cache-Control: no-store`` so a cached shell can never
    carry a stale token. Static assets keep normal caching semantics.
    """
    dist = _WEB_DIST
    if not (dist / "index.html").is_file():
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    def _index_response() -> HTMLResponse:
        shell = (dist / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            inject_session_meta(shell, session_token),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        # The SPA fallback must never answer API paths: unknown /api/* routes
        # get a JSON 404, not index.html.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = dist / full_path
        if full_path and candidate.is_file():
            if candidate.name == "index.html":
                return _index_response()
            return FileResponse(candidate)
        return _index_response()



_default_app: FastAPI | None = None


def __getattr__(name: str):
    """Build the module-level ``app`` on first use, not at import.

    Importing this module must not open the default database: ``main()``
    runs the cloud-sync data-dir check first (ADR 0011, S4) and only then
    builds the app. ``uvicorn psychtool.server.app:app`` still works.
    """
    global _default_app
    if name == "app":
        if _default_app is None:
            _default_app = create_app()
        return _default_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
