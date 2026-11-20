from psychtool.core.intake_claims import accept_suggestion, suggest_claims
from psychtool.core.workspace import import_material, init_workspace


def test_suggestions_are_literal_and_source_bound(tmp_path):
    ws = init_workspace(tmp_path / "case", case_id="case")
    import_material(ws, material_id="intake", title="Intake", provider="client", date="2026-11-01", text="Reported trouble sleeping.\n\nStart date unknown.")
    candidates = suggest_claims(ws, "intake", provider_role="self_report")
    assert [c.source_passage_id for c in candidates] == ["p001", "p002"]
    assert candidates[0].text == candidates[0].source_text
    assert candidates[0].event_time is None
    candidates[0].topic = "sleep"
    claim = accept_suggestion(ws, candidates[0])
    assert claim.topic == "sleep"
    assert claim.verification_status == "pending"
    assert claim.source_document_id == "intake"
