"""FastAPI application factory and routes.

Serves the JSON API under ``/api`` and, when a production build exists in
``web/dist``, serves the React SPA with client-side routing fallback. During
development the SPA is served by Vite (see ``web/vite.config.ts``), which
proxies ``/api`` to this server.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError

from psychtool import __version__
from psychtool.core.claims import list_claims
from psychtool.core.intake_claims import ClaimSuggestion, accept_suggestion, suggest_claims
from psychtool.core.ingest import import_upload, MAX_UPLOAD_BYTES
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
from psychtool.core.workspace import get_known_names, list_materials, set_known_names
from psychtool.config import load_config
from psychtool.gateway.client import (
    EgressOutputBlockedError,
    NetworkForbiddenError,
    send_approved,
)
from psychtool.gateway.http import http_transport

# Project root is two levels up from psychtool/server/app.py.
_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
_DEFAULT_WORKSPACES_DIR = str(Path(__file__).resolve().parents[2] / "local-data" / "workspaces")


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


def _workspaces_root() -> Path:
    return Path(os.environ.get("PSYCHTOOL_WORKSPACES_DIR", _DEFAULT_WORKSPACES_DIR))


def _workspace_path(case_id: str) -> Path:
    """Resolve a workspace directory under the configured root, never outside it."""
    root = _workspaces_root().resolve()
    candidate = (root / case_id).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=400, detail="invalid case id")
    return candidate


def create_app() -> FastAPI:
    app = FastAPI(title="psychtool", version=__version__)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request, exc) -> JSONResponse:
        _ = request, exc
        return JSONResponse(status_code=400, content={"detail": "invalid request"})

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
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/workspaces")
    def workspaces() -> list[dict]:
        root = _workspaces_root()
        if not root.is_dir():
            return []
        return [
            {"case_id": d.name}
            for d in sorted(root.iterdir())
            if d.is_dir() and (d / "meta.json").is_file()
        ]

    @app.get("/api/workspaces/{case_id}/materials")
    def materials(case_id: str) -> list[dict]:
        return [m.model_dump() for m in list_materials(_workspace_path(case_id))]

    @app.post("/api/workspaces/{case_id}/materials")
    async def upload_material(case_id: str, file: UploadFile = File(...),
                              material_id: str = Form(...), title: str = Form(...),
                              provider: str = Form(...), date: str = Form(...)) -> dict:
        try:
            data = await file.read(MAX_UPLOAD_BYTES + 1)
            material, findings = import_upload(
                _workspace_path(case_id), filename=file.filename or "", data=data,
                material_id=material_id, title=title, provider=provider, date=date,
            )
        except (UnicodeError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"material": material.model_dump(), "identifier_findings": findings,
                "requires_human_review": True}

    @app.get("/api/workspaces/{case_id}/claims")
    def claims(case_id: str) -> list[dict]:
        return [c.model_dump() for c in list_claims(_workspace_path(case_id))]

    @app.get("/api/workspaces/{case_id}/materials/{material_id}/suggestions")
    def claim_suggestions(case_id: str, material_id: str, provider_role: str) -> list[dict]:
        try:
            return [s.model_dump() for s in suggest_claims(
                _workspace_path(case_id), material_id, provider_role=provider_role
            )]
        except (KeyError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/workspaces/{case_id}/claims")
    def accept_claim(case_id: str, body: ClaimSuggestion) -> dict:
        try:
            return accept_suggestion(_workspace_path(case_id), body).model_dump()
        except (KeyError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/workspaces/{case_id}/names")
    def names(case_id: str) -> dict:
        return {"names": list(get_known_names(_workspace_path(case_id)))}

    @app.put("/api/workspaces/{case_id}/names")
    def put_names(case_id: str, body: NamesPayload) -> dict:
        return {"names": list(set_known_names(_workspace_path(case_id), body.names))}

    @app.get("/api/workspaces/{case_id}/sections")
    def sections(case_id: str, template_id: str) -> list[dict]:
        return section_states(_workspace_path(case_id), template_id)

    @app.put("/api/workspaces/{case_id}/sections/{section_id}")
    def put_section(case_id: str, section_id: str, body: SectionPayload) -> dict:
        try:
            draft = save_section(
                _workspace_path(case_id),
                template_id=body.template_id,
                template_version=body.template_version,
                section_id=section_id,
                text=body.text,
                claim_ids=body.claim_ids,
                status=body.status,
                reviewer=body.reviewer,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return draft.model_dump()

    @app.post("/api/workspaces/{case_id}/egress/prepare")
    def prepare_egress(case_id: str, body: PrepareEgressPayload) -> dict:
        try:
            workspace = _workspace_path(case_id)
            prompt, source_refs = build_section_request_input(
                workspace,
                template_id=body.template_id,
                template_version=body.template_version,
                section_id=body.section_id,
                claim_ids=body.claim_ids,
                instructions=body.instructions,
            )
            request = prepare_egress_request(
                workspace,
                prompt=prompt,
                purpose=body.purpose,
                config=load_config(),
                source_refs=source_refs,
            )
        except (EgressBlockedError, KeyError, ValueError, ValidationError, OSError) as exc:
            raise HTTPException(status_code=400, detail="invalid egress request") from exc
        return _egress_response(request)

    @app.get("/api/workspaces/{case_id}/egress/{request_id}")
    def get_egress(case_id: str, request_id: str) -> dict:
        try:
            request = get_egress_request(_workspace_path(case_id), request_id)
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
        workspace = _workspace_path(case_id)
        try:
            if body.reviewer is not None:
                request = approve_human(
                    workspace,
                    request_id,
                    reviewer=body.reviewer,
                    content_hash=body.content_hash,
                )
            else:
                request = approve_synthetic(
                    workspace,
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
        return _egress_response(request)

    @app.post("/api/workspaces/{case_id}/egress/{request_id}/send")
    def send_egress(case_id: str, request_id: str) -> dict:
        try:
            text = send_approved(
                _workspace_path(case_id),
                request_id,
                config=load_config(),
                transport=http_transport,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="egress request not found") from exc
        except NetworkForbiddenError as exc:
            raise HTTPException(status_code=403, detail="model network access forbidden") from exc
        except EgressOutputBlockedError as exc:
            raise HTTPException(status_code=422, detail="model output blocked") from exc
        except (EgressStateError, EgressStaleError) as exc:
            raise HTTPException(status_code=409, detail="egress request state conflict") from exc
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail="invalid egress request") from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(status_code=502, detail="model request failed") from exc
        return {"request_id": request_id, "status": "sent", "text": text}

    @app.post("/api/workspaces/{case_id}/sections/{section_id}/generate")
    def generate(case_id: str, section_id: str) -> None:
        _ = case_id, section_id
        raise HTTPException(
            status_code=410,
            detail="Direct generation is gone; use egress prepare, approve, and send.",
        )

    _mount_spa(app)
    return app


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA if ``web/dist`` exists, with SPA fallback."""
    dist = _WEB_DIST
    if not (dist / "index.html").is_file():
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
