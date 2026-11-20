"""Reversible identifier redaction and re-identification scanning."""

from psychtool.core.redact import (
    find_identifiers,
    gate_pii,
    redact_text,
    restore_text,
    SAFE_HARBOR_18,
)


def test_safe_harbor_has_eighteen_categories():
    assert len(SAFE_HARBOR_18) == 18


def test_redact_and_restore_roundtrip():
    text = "Contact Jane Doe at (312) 555-0142 or jane.doe@example.com."
    redacted, token_map = redact_text(text, known_names=("Jane Doe",))
    assert "(312) 555-0142" not in redacted
    assert "jane.doe@example.com" not in redacted
    assert "Jane Doe" not in redacted
    assert restore_text(redacted, token_map) == text


def test_redact_preserves_semantic_roles():
    text = "The client's mother reported bedtime resistance."
    redacted, _ = redact_text(text, known_names=("Jane Doe",))
    assert "mother" in redacted
    assert "client" in redacted.lower()


def test_ssn_not_relabelled_telephone():
    redacted, token_map = redact_text("SSN 123-45-6789 and phone 312-555-0142.")
    assert "[[SSN_" in redacted
    assert "[[TELEPHONE_" in redacted
    assert "123-45-6789" in token_map.values()
    assert "312-555-0142" in token_map.values()


def test_dates_are_redacted_but_years_can_remain():
    redacted, _ = redact_text("Born on 2011-03-11 in March 2011.")
    assert "2011-03-11" not in redacted
    # the standalone year is allowed to remain under Safe Harbor
    assert "2011" in redacted


def test_ages_over_89_are_redacted():
    redacted, _ = redact_text("The client is 91 years old.")
    assert "91 years" not in redacted
    assert "[[AGE_OVER_89_" in redacted


def test_known_names_redacted_case_insensitively():
    redacted, _ = redact_text("jane doe visited.", known_names=("Jane Doe",))
    assert "jane doe" not in redacted
    assert "[[NAME_" in redacted


def test_find_identifiers_reports_categories():
    text = "Reach me at 312-555-0142 or bob@example.com, IP 10.0.0.1."
    findings = find_identifiers(text)
    kinds = {f["category"] for f in findings}
    assert {"telephone", "email", "ip_address"} <= kinds


def test_gate_pii_empty_for_clean_text():
    assert gate_pii("The client enjoys math and reading.") == []


def test_restore_unknown_token_left_untouched():
    assert restore_text("kept [[UNKNOWN_9]] here", {}) == "kept [[UNKNOWN_9]] here"


def test_no_false_positive_on_plain_numbers():
    # a 5-digit number is treated as a zip (heuristic) but nothing else trips
    redacted, _ = redact_text("The room number is 202.")
    assert "202" in redacted
