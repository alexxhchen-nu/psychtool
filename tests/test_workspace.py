"""Workspace init + material import (version-immutable storage)."""

import json

import pytest

from psychtool.core.workspace import (
    WorkspaceExistsError,
    init_workspace,
    import_material,
    latest_version,
    set_known_names,
    get_known_names,
)


SAMPLE_TEXT = "背景段落一。\n\n背景段落二。\n\n背景段落三。"


def test_init_creates_meta_and_subdirs(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    meta = json.loads((ws / "meta.json").read_text(encoding="utf-8"))
    assert meta["case_id"] == "case-a"
    assert meta["data_tier"] == "synthetic"
    for sub in ("materials", "claims", "drafts", "reviews"):
        assert (ws / sub).is_dir()


def test_init_twice_raises(tmp_path):
    p = tmp_path / "case-a"
    init_workspace(p, case_id="case-a")
    with pytest.raises(WorkspaceExistsError):
        init_workspace(p, case_id="case-a")


def test_import_splits_text_into_passages(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    mat = import_material(
        ws,
        material_id="doc-1",
        title="访谈记录",
        provider="本人",
        date="2026-10-01",
        text=SAMPLE_TEXT,
    )
    assert mat.version == 1
    assert [p.id for p in mat.passages] == ["p001", "p002", "p003"]
    assert mat.passages[0].text == "背景段落一。"
    assert mat.provider == "本人"
    assert mat.case_id == "case-a"


def test_import_writes_versioned_file(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text=SAMPLE_TEXT)
    assert (ws / "materials" / "doc-1.v1.json").is_file()


def test_reimport_creates_new_version_and_keeps_old(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text=SAMPLE_TEXT)
    import_material(ws, material_id="doc-1", title="t", provider="p", date="2026-10-02", text="修订后的唯一段落。")
    assert (ws / "materials" / "doc-1.v1.json").is_file()
    assert (ws / "materials" / "doc-1.v2.json").is_file()
    assert latest_version(ws, "doc-1") == 2
    # old version still readable and unchanged
    old = json.loads((ws / "materials" / "doc-1.v1.json").read_text(encoding="utf-8"))
    assert old["version"] == 1
    assert len(old["passages"]) == 3


def test_material_requires_provider(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    with pytest.raises(ValueError):
        import_material(
            ws, material_id="doc-1", title="t", provider="", date="2026-10-01", text=SAMPLE_TEXT
        )


def test_import_binds_material_to_workspace_case(tmp_path):
    # import_material derives case_id from the workspace meta, not from input;
    # a material can never be created under a foreign case id via this layer.
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    mat = import_material(
        ws, material_id="doc-1", title="t", provider="p", date="2026-10-01", text=SAMPLE_TEXT
    )
    assert mat.case_id == "case-a"


def test_set_and_get_known_names(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    assert get_known_names(ws) == ()
    set_known_names(ws, ["Jane Doe", "Dr. Smith", "jane doe", ""])
    assert get_known_names(ws) == ("Dr. Smith", "Jane Doe")
