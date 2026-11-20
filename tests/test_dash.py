"""dash TUI smoke tests (mount + render; no re-test of core logic)."""

import asyncio

from psychtool.core.workspace import init_workspace
from psychtool.core.claims import add_claim
from psychtool.tui.app import DashApp


def _seed_ws(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    add_claim(
        ws, claim_id="c1", source_document_id="doc-1", source_version=1,
        source_passage_id="p001", provider_role="self_report",
        observation_setting="intake", record_time="2026-10-01",
        category="client_statement", topic="t", text="本人报告入睡困难。",
    )
    return ws


async def _run(app):
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#claims-table") is not None
        assert app.query_one("#review-text") is not None
        assert app.query_one("#drafts-text") is not None
        # claims table populated
        table = app.query_one("#claims-table")
        assert table.row_count == 1


def test_dash_mounts_and_renders(tmp_path):
    ws = _seed_ws(tmp_path)
    app = DashApp(str(ws))
    asyncio.run(_run(app))


def test_dash_empty_workspace(tmp_path):
    ws = init_workspace(tmp_path / "case-a", case_id="case-a")
    app = DashApp(str(ws))

    async def _run_empty(app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#claims-table").row_count == 0

    asyncio.run(_run_empty(app))
