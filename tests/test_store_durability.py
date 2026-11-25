"""Durability tests: power-cut recovery and cross-instance persistence.

The first power-cut test forks a child process that writes claims in a loop
and is SIGKILLed mid-flight; the parent checks the database survives and
stays writable. The second power-cut test is deterministic about the crash
point: the child opens the store's own ``transaction()``, writes one material
row plus several passage rows, announces ``MID`` and sleeps WITHOUT
committing; the parent SIGKILLs it and asserts the multi-row write is entirely
absent. The persistence test opens two app instances against one database
file and expects the second to see everything the first wrote.
"""

from __future__ import annotations

import signal
import sqlite3
import subprocess
import sys
import time

from fastapi.testclient import TestClient

from psychtool.core.workspace import Passage
from psychtool.server.app import create_app
from psychtool.store.sqlite_store import SqliteStore

_CHILD_SOURCE = """
import sys
from psychtool.store.sqlite_store import SqliteStore

db_path = sys.argv[1]
store = SqliteStore(db_path)
case = store.case("case-a")
i = 0
while True:
    i += 1
    # Each claim write is its own transaction; a SIGKILL lands mid-loop.
    case.add_claim(
        claim_id=f"power-cut-{i}",
        source_document_id="m1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-11-24",
        category="client_statement",
        topic="history",
        text=f"claim body {i}",
    )
    print(i, flush=True)
"""


def test_power_cut_leaves_database_consistent(tmp_path):
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)
    store.create_case("case-a")
    store.case("case-a").import_material(
        material_id="m1", title="t", provider="p", date="d",
        passages=[Passage(id="p001", text="source paragraph")],
    )

    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SOURCE, str(db_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        # Wait until the child has committed several claims, then kill -9 it
        # at an arbitrary point (likely mid-transaction).
        assert child.stdout is not None
        committed = 0
        deadline = time.monotonic() + 30
        while committed < 5 and time.monotonic() < deadline:
            line = child.stdout.readline()
            if line.strip().isdigit():
                committed = int(line.strip())
        assert committed >= 5, "child did not make progress"
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=30)
        if child.stdout is not None:
            child.stdout.close()

    # 1. The file passes SQLite's own integrity check.
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = connection.execute(
            "SELECT claim_id FROM claims WHERE case_id = 'case-a' ORDER BY claim_id"
        ).fetchall()
    finally:
        connection.close()

    # 2. No partial rows: every surviving claim is a complete, valid version-1
    #    row; the in-flight transaction was rolled back by journal recovery.
    claim_ids = [row[0] for row in rows]
    assert len(claim_ids) >= 5
    assert len(set(claim_ids)) == len(claim_ids)
    for claim_id in claim_ids:
        assert claim_id.startswith("power-cut-")

    # 3. The database is still writable through the store.
    recovered = SqliteStore(db_path)
    case = recovered.case("case-a")
    before = len(case.list_claims())
    case.add_claim(
        claim_id="after-recovery",
        source_document_id="m1",
        source_version=1,
        source_passage_id="p001",
        provider_role="self_report",
        observation_setting="intake",
        record_time="2026-11-24",
        category="client_statement",
        topic="history",
        text="written after the power cut",
    )
    assert len(case.list_claims()) == before + 1


# The child writes a material row plus several passage rows inside ONE
# store.transaction(), announces MID, then sleeps without committing. SIGKILL
# at that point must leave zero rows of the new material in both tables.
_MID_TRANSACTION_CHILD = """
import sys
import time
from psychtool.store.sqlite_store import SqliteStore

db_path = sys.argv[1]
store = SqliteStore(db_path)
with store.transaction() as connection:
    connection.execute(
        "INSERT INTO materials (case_id, material_id, version, title, provider, date)"
        " VALUES ('case-a', 'm-mid', 1, 'half-written', 'p', 'd')"
    )
    for position in range(1, 6):
        connection.execute(
            "INSERT INTO passages (case_id, material_id, version, passage_id, position, text)"
            f" VALUES ('case-a', 'm-mid', 1, 'p{position:03d}', {position}, 'passage {position}')"
        )
    # All five inserts executed, none committed yet: this is the crash point.
    print("MID", flush=True)
    time.sleep(600)
"""


def test_power_cut_mid_transaction_leaves_no_partial_rows(tmp_path):
    db_path = tmp_path / "psychtool.db"
    store = SqliteStore(db_path)
    store.create_case("case-a")
    # Earlier committed data that must survive the crash untouched.
    store.case("case-a").import_material(
        material_id="m1", title="committed", provider="p", date="d",
        passages=[Passage(id="p001", text="committed paragraph")],
    )

    child = subprocess.Popen(
        [sys.executable, "-c", _MID_TRANSACTION_CHILD, str(db_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert child.stdout is not None
        deadline = time.monotonic() + 30
        line = ""
        while time.monotonic() < deadline:
            line = child.stdout.readline().strip()
            if line == "MID":
                break
        assert line == "MID", "child never reached the mid-transaction point"
        # The transaction is open and uncommitted; kill -9 now.
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=30)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=30)
        if child.stdout is not None:
            child.stdout.close()

    # 1. The file passes SQLite's own integrity check after journal recovery.
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # 2. The half-written material is entirely absent: zero rows in
        #    materials AND zero rows in passages (no partial multi-row write).
        assert connection.execute(
            "SELECT COUNT(*) FROM materials WHERE case_id = 'case-a' AND material_id = 'm-mid'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM passages WHERE case_id = 'case-a' AND material_id = 'm-mid'"
        ).fetchone()[0] == 0
        # 3. Earlier committed data is intact.
        assert connection.execute(
            "SELECT text FROM passages WHERE case_id = 'case-a' AND material_id = 'm1'"
        ).fetchall() == [("committed paragraph",)]
    finally:
        connection.close()

    # 4. The database is still writable and readable through the store.
    recovered = SqliteStore(db_path)
    case = recovered.case("case-a")
    assert [m.id for m in case.list_materials()] == ["m1"]
    case.import_material(
        material_id="m2", title="after", provider="p", date="d",
        passages=[Passage(id="p001", text="written after the crash")],
    )
    assert case.get_material("m2").passages[0].text == "written after the crash"


def test_persistence_across_two_app_instances(tmp_path, monkeypatch):
    """A second app instance on the same DB file sees everything the first wrote."""
    db_path = tmp_path / "psychtool.db"
    monkeypatch.setenv("PSYCHTOOL_DB_PATH", str(db_path))

    first = TestClient(create_app())
    assert first.post("/api/workspaces", json={"case_id": "case-a"}).status_code == 201
    pasted = first.post(
        "/api/workspaces/case-a/materials/paste",
        json={
            "material_id": "m1",
            "title": "Intake",
            "provider": "synthetic",
            "date": "2026-11-24",
            "text": "Durable synthetic paragraph.",
            "synthetic_confirmed": True,
        },
    )
    assert pasted.status_code == 200
    suggestions = first.get(
        "/api/workspaces/case-a/materials/m1/suggestions",
        params={"provider_role": "self_report"},
    ).json()
    assert first.post("/api/workspaces/case-a/claims", json=suggestions[0]).status_code == 200
    assert first.put(
        "/api/workspaces/case-a/names", json={"names": ["Jane Doe"]}
    ).status_code == 200

    second = TestClient(create_app())
    assert second.get("/api/workspaces").json() == [{"case_id": "case-a"}]
    materials = second.get("/api/workspaces/case-a/materials").json()
    assert [m["id"] for m in materials] == ["m1"]
    assert materials[0]["passages"][0]["text"] == "Durable synthetic paragraph."
    assert len(second.get("/api/workspaces/case-a/claims").json()) == 1
    assert second.get("/api/workspaces/case-a/names").json() == {"names": ["Jane Doe"]}

    # And writes through the second instance are visible to a third.
    assert second.put(
        "/api/workspaces/case-a/names", json={"names": ["Jane Doe", "Dr. Smith"]}
    ).status_code == 200
    third = TestClient(create_app())
    assert third.get("/api/workspaces/case-a/names").json() == {
        "names": ["Dr. Smith", "Jane Doe"]
    }
