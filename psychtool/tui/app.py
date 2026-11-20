"""dash TUI: the main interactive interface (ADR 0006)."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

from psychtool.core.claims import list_claims, mark_status
from psychtool.core.review import review_summary
from psychtool.core.draft import list_drafts

CSS = """
Header {
    background: #1F2430;
    color: #FAF8F2;
}
Footer {
    background: #1F2430;
    color: #FAF8F2;
}
DataTable > .datatable--header {
    background: #4C6EF5;
    color: #FAF8F2;
}
"""


class DashApp(App):
    CSS = CSS
    TITLE = "psychtool"
    BINDINGS = [
        ("v", "verify", "核对通过"),
        ("c", "conflict", "冲突已查看"),
        ("p", "pending", "待核对"),
    ]

    def __init__(self, workspace_path: str):
        super().__init__()
        self.workspace = Path(workspace_path)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent("候选陈述", "审阅", "草稿"):
            with TabPane("候选陈述", id="claims"):
                yield DataTable(id="claims-table", cursor_type="row")
            with TabPane("审阅", id="review"):
                yield Static(id="review-text")
            with TabPane("草稿", id="drafts"):
                yield Static(id="drafts-text")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"工作区 {self.workspace.name}"
        self._reload_claims()
        self._reload_review()
        self._reload_drafts()

    def _reload_claims(self) -> None:
        table = self.query_one("#claims-table", DataTable)
        table.clear(columns=True)
        table.add_columns("id", "状态", "归属", "陈述")
        for c in list_claims(self.workspace):
            table.add_row(c.id, c.verification_status, c.provider_role, c.text, key=c.id)

    def _reload_review(self) -> None:
        s = review_summary(self.workspace)
        self.query_one("#review-text", Static).update(
            json.dumps(s, ensure_ascii=False, indent=2)
        )

    def _reload_drafts(self) -> None:
        drafts = list_drafts(self.workspace)
        text = "\n\n".join(d.text for d in drafts) or "（无草稿）"
        self.query_one("#drafts-text", Static).update(text)

    def _selected_claim_id(self) -> str | None:
        table = self.query_one("#claims-table", DataTable)
        if table.row_count == 0:
            return None
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        return str(row_key.value) if row_key else None

    def action_verify(self) -> None:
        self._set_status("verified")

    def action_conflict(self) -> None:
        self._set_status("conflict-viewed")

    def action_pending(self) -> None:
        self._set_status("pending")

    def _set_status(self, status: str) -> None:
        cid = self._selected_claim_id()
        if cid is None:
            return
        mark_status(self.workspace, cid, status)
        self._reload_claims()
        self._reload_review()
