"""CLI ``fields`` command: persist and list identifying names for redaction."""

from psychtool.cli.app import fields_set
from psychtool.core.workspace import get_known_names, init_workspace


def test_fields_set_persists_known_names(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    fields_set(str(ws), name=["Jane Doe", "Dr. Smith", "jane doe"])
    # case-insensitive de-duplication, sorted by lowercase
    assert get_known_names(ws) == ("Dr. Smith", "Jane Doe")
