"""Report-template manifest and content validation."""

import json
from pathlib import Path

import pytest

from psychtool.core.report_templates import load_template, list_templates, manifest_as_dict

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def test_ew_template_loads_with_stable_section_order():
    template = load_template("ew-report")
    assert template.version == 1
    assert [section.id for section in template.sections] == [
        "report_header",
        "identifying_information",
        "reason_for_testing",
        "procedures",
        "executive_summary",
        "diagnostic_impressions",
        "recommendations",
        "background_information",
        "testing_results",
        "score_summary",
    ]


def test_template_files_are_utf8_and_clean_of_conversion_residue():
    markdown = (TEMPLATES / "EW Report Template.md").read_text(encoding="utf-8")
    assert "CLIENT LAST" not in markdown
    assert "鈥" not in markdown
    assert "(630) 206-4060" not in markdown
    assert "Illinois" not in markdown


def test_source_snapshot_remains_separate_from_application_copy():
    template = load_template("ew-report")
    assert template.source_snapshot.endswith(".txt")
    assert template.markdown_file.endswith(".md")
    assert template.source_snapshot != template.markdown_file


def test_high_consequence_sections_require_clinician_review():
    template = load_template("ew-report")
    gates = {section.id: section.review_gate for section in template.sections}
    for section_id in ("diagnostic_impressions", "recommendations", "testing_results", "score_summary"):
        assert gates[section_id] == "licensed_clinician"


def test_all_markdown_placeholders_are_declared():
    template = load_template("ew-report")
    assert {field.id for field in template.fields} >= {"client_name", "evaluator_name"}


def test_manifest_api_shape_omits_local_file_paths():
    public = manifest_as_dict(load_template("ew-report"))
    assert "source_snapshot" not in public
    assert "markdown_file" not in public
    assert public["template_id"] == "ew-report"


def test_list_templates_returns_available_manifests():
    assert [template.template_id for template in list_templates()] == ["ew-report"]


def test_duplicate_section_ids_are_rejected():
    tmp_path = ROOT / ".scratch" / "template-test"
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((TEMPLATES / "ew-report.template.json").read_text(encoding="utf-8-sig"))
    manifest["sections"][1]["id"] = manifest["sections"][0]["id"]
    (tmp_path / "EW Report Template.md").write_text(
        (TEMPLATES / "EW Report Template.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "EW Report Template.txt").write_text("source", encoding="utf-8")
    (tmp_path / "ew-report.template.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="section ids must be unique"):
        load_template("ew-report", templates_dir=tmp_path)
