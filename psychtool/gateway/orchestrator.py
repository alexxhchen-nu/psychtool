"""Reusable orchestration for the strict prepare/approve/send egress pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from psychtool.config import Config
from psychtool.core.egress import (
    EgressPurpose,
    EgressRequest,
    EgressRunner,
    SourceRef,
    approve_human,
    approve_synthetic,
    prepare_egress_request,
)
from psychtool.gateway.client import send_approved

Transport = Callable[[Config, dict], str]
RequestCallback = Callable[[EgressRequest], None]
ReviewConfirmation = Callable[[EgressRequest], bool]


class EgressApprovalRequired(RuntimeError):
    """Raised after preparation when this invocation has no valid approval choice."""


class EgressReviewDeclined(RuntimeError):
    """Raised when a human declines the exact prepared request."""


@dataclass(frozen=True)
class HumanApproval:
    reviewer: str
    confirm: ReviewConfirmation


@dataclass(frozen=True)
class SyntheticApproval:
    reason: str


ApprovalChoice = HumanApproval | SyntheticApproval | None


def orchestrate_egress(
    *,
    workspace: Path,
    prompt: str,
    purpose: EgressPurpose,
    source_refs: list[SourceRef],
    config: Config,
    approval: ApprovalChoice,
    transport: Transport,
    on_prepared: RequestCallback | None = None,
) -> str:
    """Prepare, explicitly approve, and send one complete model request.

    A missing approval deliberately stops after persistence so callers can show
    the redacted request without creating an implicit send path.
    """
    request = prepare_egress_request(
        Path(workspace),
        prompt=prompt,
        purpose=purpose,
        config=config,
        source_refs=source_refs,
    )
    if on_prepared is not None:
        on_prepared(request)

    if approval is None:
        raise EgressApprovalRequired("egress request requires explicit approval")
    if isinstance(approval, HumanApproval):
        if not approval.confirm(request):
            raise EgressReviewDeclined("egress request was not approved")
        approve_human(
            workspace,
            request.request_id,
            reviewer=approval.reviewer,
            content_hash=request.content_hash,
        )
    else:
        approve_synthetic(
            workspace,
            request.request_id,
            reason=approval.reason,
            content_hash=request.content_hash,
        )

    return send_approved(
        workspace,
        request.request_id,
        config=config,
        transport=transport,
    )


@dataclass(frozen=True)
class EgressOrchestrator(EgressRunner):
    """A configured strict runner for core draft, judge, and eval workflows."""

    config: Config
    approval: ApprovalChoice
    transport: Transport
    on_prepared: RequestCallback | None = None

    def run(
        self,
        *,
        workspace: Path,
        prompt: str,
        purpose: EgressPurpose,
        source_refs: list[SourceRef],
    ) -> str:
        return orchestrate_egress(
            workspace=workspace,
            prompt=prompt,
            purpose=purpose,
            source_refs=source_refs,
            config=self.config,
            approval=self.approval,
            transport=self.transport,
            on_prepared=self.on_prepared,
        )
