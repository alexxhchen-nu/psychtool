"""Report template manifest models and loading.

Report templates live in the repository-level ``templates`` directory. The
plain-text export remains the source snapshot; the Markdown and JSON manifest
are the application-facing, reviewable representation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")


class TemplateField(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    required: bool = False
    review_required: bool = False


class TemplateSection(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    level: int = Field(default=1, ge=1, le=3)
    required: bool = False
    content_types: list[
        Literal[
            "fixed_text",
            "field_input",
            "source_fact",
            "clinical_interpretation",
            "diagnostic_conclusion",
            "recommendation",
            "score_table",
        ]
    ]
    allowed_sources: list[str] = Field(default_factory=list)
    review_gate: Literal["standard", "licensed_clinician"] = "standard"


class ReportTemplate(BaseModel):
    template_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: int = Field(ge=1)
    report_type: str
    title: str
    source_snapshot: str
    markdown_file: str
    fields: list[TemplateField]
    sections: list[TemplateSection]

    @model_validator(mode="after")
    def unique_ids(self) -> "ReportTemplate":
        field_ids = [field.id for field in self.fields]
        section_ids = [section.id for section in self.sections]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("template field ids must be unique")
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("template section ids must be unique")
        return self


def load_template(template_id: str, *, templates_dir: Path = TEMPLATES_DIR) -> ReportTemplate:
    path = Path(templates_dir) / f"{template_id}.template.json"
    if not path.is_file():
        raise KeyError(f"unknown report template: {template_id}")
    template = ReportTemplate.model_validate_json(path.read_text(encoding="utf-8-sig"))
    _validate_files(template, path.parent)
    return template


def list_templates(*, templates_dir: Path = TEMPLATES_DIR) -> list[ReportTemplate]:
    return [
        load_template(path.name.removesuffix(".template.json"), templates_dir=templates_dir)
        for path in sorted(Path(templates_dir).glob("*.template.json"))
    ]


def _validate_files(template: ReportTemplate, directory: Path) -> None:
    markdown_path = directory / template.markdown_file
    source_path = directory / template.source_snapshot
    if not markdown_path.is_file() or not source_path.is_file():
        raise ValueError("template markdown and source snapshot must exist")

    markdown = markdown_path.read_text(encoding="utf-8")
    declared_fields = {field.id for field in template.fields}
    used_fields = set(_PLACEHOLDER_RE.findall(markdown))
    undeclared = sorted(used_fields - declared_fields)
    unused = sorted(declared_fields - used_fields)
    if undeclared:
        raise ValueError(f"undeclared placeholders: {undeclared}")
    if unused:
        raise ValueError(f"declared fields not used by markdown: {unused}")

    for section in template.sections:
        marker = f'<!-- section:{section.id} -->'
        if marker not in markdown:
            raise ValueError(f"missing section marker: {section.id}")


def manifest_as_dict(template: ReportTemplate) -> dict:
    """Return an API-safe manifest without local filesystem paths."""
    data = json.loads(template.model_dump_json())
    data.pop("source_snapshot", None)
    data.pop("markdown_file", None)
    return data
