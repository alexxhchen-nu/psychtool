"""PT-20 chunk 2 (GROK-51): egress lineage records cited sentence evidence ids.

Preparing an egress request from a claim that cites stored evidence must
persist exactly those ids on the claim's SourceRef (and they must survive a
reload of the request). The protected-content screen also covers the cited
evidence quotes, not only the claim's own text.
"""

from __future__ import annotations

import pytest

from psychtool.core.egress import (
    EgressProtectedContentError,
    SourceRef,
    prepare_egress_request,
)
from psychtool.core.extract import RuleExtractor
from psychtool.core.sections import build_section_request_input
from psychtool.core.workspace import Passage
from psychtool.config import Config
from psychtool.store.sqlite_store import SqliteStore

PASSAGE_TEXT = "Teacher says he reads slowly in class."


@pytest.fixture
def store(tmp_path):
    return SqliteStore(tmp_path / "psychtool.db")


@pytest.fixture
def case(store):
    store.create_case("case-a")
    return store.case("case-a")


def _config():
    return Config(
        base_url="https://provider.invalid/v1",
        model="model-1",
        data_tier="synthetic",
        api_key="must-not-persist",
    )


def _seed_claim_with_evidence(case):
    case.import_material(
        material_id="m1", title="Note", provider="synthetic", date="2026-11-24",
        passages=[Passage(id="p001", text=PASSAGE_TEXT)],
    )
    case.refresh_evidence(RuleExtractor())
    evidence_ids = case.active_evidence_ids_by_passage("m1", 1)["p001"]
    assert len(evidence_ids) >= 1
    case.add_claim(
        claim_id="c1",
        source_document_id="m1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-11-24",
        category="client_statement",
        topic="history",
        text=PASSAGE_TEXT,
        evidence_ids=list(evidence_ids),
    )
    return evidence_ids


def test_build_section_request_input_carries_claim_evidence_ids(case):
    evidence_ids = _seed_claim_with_evidence(case)
    _, source_refs = build_section_request_input(
        case,
        template_id="intake-report",
        template_version=1,
        section_id="history",
        claim_ids=["c1"],
        instructions="Write the history section.",
    )
    assert len(source_refs) == 1
    ref = source_refs[0]
    assert ref.kind == "claim"
    assert ref.id == "c1"
    assert ref.evidence_ids == evidence_ids


def test_prepared_request_persists_cited_evidence_ids(case, store):
    """Lineage guard: fails if the cited ids are dropped anywhere."""
    evidence_ids = _seed_claim_with_evidence(case)
    prompt, source_refs = build_section_request_input(
        case,
        template_id="intake-report",
        template_version=1,
        section_id="history",
        claim_ids=["c1"],
        instructions="Write the history section.",
    )
    request = prepare_egress_request(
        case,
        prompt=prompt,
        purpose="section_generation",
        config=_config(),
        source_refs=source_refs,
    )
    claim_refs = [ref for ref in request.source_refs if ref.kind == "claim"]
    assert len(claim_refs) == 1
    assert claim_refs[0].evidence_ids == evidence_ids
    # The stored row keeps them: a fresh load shows exactly the same ids.
    reloaded = case.get_egress_request(request.request_id)
    assert [ref.model_dump() for ref in reloaded.source_refs] == [
        ref.model_dump() for ref in request.source_refs
    ]
    assert reloaded.source_refs[0].evidence_ids == evidence_ids


def test_material_refs_default_to_empty_evidence_ids():
    ref = SourceRef(kind="material", id="m1", version=1)
    assert ref.evidence_ids == []


def test_protected_screen_covers_cited_evidence_quotes(case, monkeypatch):
    """A protected quote behind a cited evidence id refuses the prepare,
    even when the claim's own text is clean."""
    evidence_ids = _seed_claim_with_evidence(case)
    _, source_refs = build_section_request_input(
        case,
        template_id="intake-report",
        template_version=1,
        section_id="history",
        claim_ids=["c1"],
        instructions="Write the history section.",
    )
    import psychtool.core.protected as protected

    screened: list[str] = []
    real_is_protected = protected.is_protected

    def spy(text: str) -> bool:
        screened.append(text)
        return real_is_protected(text)

    monkeypatch.setattr(protected, "is_protected", spy)
    request = prepare_egress_request(
        case,
        prompt="synthetic prompt",
        purpose="section_generation",
        config=_config(),
        source_refs=source_refs,
    )
    assert request.status == "prepared"
    # Every cited quote was screened (they are the passage sentences).
    for evidence_id in evidence_ids:
        quote = next(
            row["quote"]
            for row in case.list_evidence()
            if row["id"] == evidence_id
        )
        assert quote in screened

    def boom(text: str) -> bool:
        raise RuntimeError("checker down")

    monkeypatch.setattr(protected, "is_protected", boom)
    with pytest.raises(EgressProtectedContentError):
        prepare_egress_request(
            case,
            prompt="synthetic prompt",
            purpose="section_generation",
            config=_config(),
            source_refs=source_refs,
        )
