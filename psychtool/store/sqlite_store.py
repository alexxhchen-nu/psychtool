"""SQLite case store (ADR 0010): one local file, per-case isolation.

Design rules enforced here, not by convention:

- every case-owned table carries ``case_id`` in its primary key / foreign
  keys, and every statement filters on it;
- the only way to reach case data is :class:`CaseStore`, obtained from a
  validated, existing case id via :meth:`SqliteStore.case`; there is no
  unscoped query helper;
- writes that must be all-or-nothing (multi-row imports, material versions)
  run inside one transaction, so a crash leaves the database either fully
  before or fully after the change;
- material and claim versions are immutable: a change appends a new version
  row instead of updating;
- every parameter is bound through ``?`` placeholders; no value is ever
  string-formatted into SQL.

Durability: WAL journal mode with ``synchronous=FULL`` and
``foreign_keys=ON`` on every connection. Schema is created and versioned on
open through ``PRAGMA user_version``.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from psychtool.core.claims import Claim
from psychtool.core.sections import SectionDraft
from psychtool.core.workspace import Material, Passage

# Mirrors the server-side case-id rule: no path separators, no SQL/LIKE
# metacharacters, bounded length. Validated before any SQL runs.
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Mirrors the material-id rule used by the ingest path.
MATERIAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_SCHEMA_VERSION = 1

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS cases (
        case_id     TEXT PRIMARY KEY CHECK (length(case_id) BETWEEN 1 AND 64),
        data_tier   TEXT NOT NULL CHECK (data_tier IN ('synthetic', 'real')),
        created_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS known_names (
        case_id TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
        name    TEXT NOT NULL,
        PRIMARY KEY (case_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS materials (
        case_id    TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
        material_id TEXT NOT NULL,
        version    INTEGER NOT NULL CHECK (version >= 1),
        title      TEXT NOT NULL,
        provider   TEXT NOT NULL,
        date       TEXT NOT NULL,
        PRIMARY KEY (case_id, material_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS passages (
        case_id     TEXT NOT NULL,
        material_id TEXT NOT NULL,
        version     INTEGER NOT NULL,
        passage_id  TEXT NOT NULL,
        position    INTEGER NOT NULL CHECK (position >= 1),
        text        TEXT NOT NULL,
        PRIMARY KEY (case_id, material_id, version, passage_id),
        FOREIGN KEY (case_id, material_id, version)
            REFERENCES materials(case_id, material_id, version) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS claims (
        case_id              TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
        claim_id             TEXT NOT NULL,
        version              INTEGER NOT NULL CHECK (version >= 1),
        source_document_id   TEXT NOT NULL,
        source_version       INTEGER NOT NULL,
        source_passage_id    TEXT NOT NULL,
        provider_role        TEXT NOT NULL,
        observation_setting  TEXT NOT NULL,
        record_time          TEXT NOT NULL,
        event_time           TEXT,
        category             TEXT NOT NULL,
        topic                TEXT NOT NULL,
        text                 TEXT NOT NULL,
        verification_status  TEXT NOT NULL
            CHECK (verification_status IN ('pending', 'verified', 'conflict-viewed')),
        PRIMARY KEY (case_id, claim_id, version),
        -- Structural isolation: a claim can only cite a passage that exists
        -- inside the same case, so no code path can cross case boundaries.
        FOREIGN KEY (case_id, source_document_id, source_version, source_passage_id)
            REFERENCES passages(case_id, material_id, version, passage_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sections (
        case_id          TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
        template_id      TEXT NOT NULL,
        section_id       TEXT NOT NULL,
        version          INTEGER NOT NULL CHECK (version >= 1),
        template_version INTEGER NOT NULL,
        text             TEXT NOT NULL,
        claim_ids        TEXT NOT NULL,
        status           TEXT NOT NULL
            CHECK (status IN ('empty', 'draft', 'needs_review', 'approved')),
        review_gate      TEXT NOT NULL CHECK (review_gate IN ('standard', 'licensed_clinician')),
        reviewer         TEXT,
        updated_at       TEXT NOT NULL,
        PRIMARY KEY (case_id, template_id, section_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS egress_requests (
        case_id               TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
        request_id            TEXT NOT NULL,
        purpose               TEXT NOT NULL,
        data_tier             TEXT NOT NULL,
        provider_base_url     TEXT NOT NULL,
        envelope              TEXT NOT NULL,
        source_refs           TEXT NOT NULL,
        identifier_categories TEXT NOT NULL,
        content_hash          TEXT NOT NULL,
        status                TEXT NOT NULL
            CHECK (status IN ('prepared', 'approved', 'sent', 'invalidated')),
        approval_mode         TEXT CHECK (approval_mode IN ('human', 'synthetic_auto')),
        reviewer              TEXT,
        approval_reason       TEXT,
        prepared_at           TEXT NOT NULL,
        approved_at           TEXT,
        sent_at               TEXT,
        send_lock_owner       TEXT,
        transition_lock_owner TEXT,
        PRIMARY KEY (case_id, request_id)
    )
    """,
)


class CaseExistsError(RuntimeError):
    """Raised when creating or importing a case that already exists."""


class UnknownCaseError(KeyError):
    """Raised when binding to a case id that does not exist."""


def default_db_path() -> Path:
    """Resolve the database path: env override, else ``local-data/psychtool.db``."""
    override = os.environ.get("PSYCHTOOL_DB_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "local-data" / "psychtool.db"


def validate_case_id(case_id: str) -> str:
    """Reject anything that is not a plain case id (path/SQL/LIKE safe)."""
    if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
        raise ValueError("invalid case id")
    return case_id


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    """The one SQLite database file. Case data is only reachable per case."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        connection = sqlite3.connect(
            str(self._path),
            isolation_level=None,  # autocommit; transactions are explicit
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        self._local.connection = connection
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
        elif version != _SCHEMA_VERSION:
            raise RuntimeError(
                f"unsupported database schema version: {version}"
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One all-or-nothing unit of work on this thread's connection."""
        connection = self._connect()
        if connection.in_transaction:
            # Nested call: join the outer transaction (savepoint-free; the
            # outermost COMMIT/ROLLBACK decides). This keeps store methods
            # composable inside one atomic unit.
            yield connection
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    # -- case registry -------------------------------------------------

    def create_case(self, case_id: str, *, data_tier: str = "synthetic") -> None:
        """Register a new case; 409-equivalent error if it already exists."""
        validate_case_id(case_id)
        try:
            with self.transaction() as connection:
                connection.execute(
                    "INSERT INTO cases (case_id, data_tier, created_at) VALUES (?, ?, ?)",
                    (case_id, data_tier, _utcnow()),
                )
        except sqlite3.IntegrityError as exc:
            raise CaseExistsError(f"case already exists: {case_id}") from exc

    def case_exists(self, case_id: str) -> bool:
        validate_case_id(case_id)
        row = self._connect().execute(
            "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        return row is not None

    def list_cases(self) -> list[str]:
        rows = self._connect().execute(
            "SELECT case_id FROM cases ORDER BY case_id"
        ).fetchall()
        return [row[0] for row in rows]

    def case(self, case_id: str) -> "CaseStore":
        """Bind to one existing case; the only door to case-owned rows."""
        validate_case_id(case_id)
        if not self.case_exists(case_id):
            raise UnknownCaseError(f"unknown case: {case_id}")
        return CaseStore(self, case_id)

    # -- JSON import ----------------------------------------------------

    def import_workspace(self, workspace: Path | str) -> str:
        """Load an ADR 0005 JSON workspace directory as one transaction.

        All or nothing: any failure rolls every inserted row back. Refuses to
        import over an existing case id. Returns the imported case id.
        """
        from psychtool.store.importer import read_json_workspace

        bundle = read_json_workspace(Path(workspace))
        case_id = bundle["case_id"]
        validate_case_id(case_id)
        if self.case_exists(case_id):
            raise CaseExistsError(f"case already exists: {case_id}")
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO cases (case_id, data_tier, created_at) VALUES (?, ?, ?)",
                (case_id, bundle["data_tier"], bundle["created_at"]),
            )
            for name in bundle["known_names"]:
                connection.execute(
                    "INSERT INTO known_names (case_id, name) VALUES (?, ?)",
                    (case_id, name),
                )
            for material in bundle["materials"]:
                connection.execute(
                    "INSERT INTO materials (case_id, material_id, version, title, provider, date)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        case_id,
                        material.id,
                        material.version,
                        material.title,
                        material.provider,
                        material.date,
                    ),
                )
                for position, passage in enumerate(material.passages, start=1):
                    connection.execute(
                        "INSERT INTO passages"
                        " (case_id, material_id, version, passage_id, position, text)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            case_id,
                            material.id,
                            material.version,
                            passage.id,
                            position,
                            passage.text,
                        ),
                    )
            for claim in bundle["claims"]:
                connection.execute(
                    "INSERT INTO claims"
                    " (case_id, claim_id, version, source_document_id, source_version,"
                    "  source_passage_id, provider_role, observation_setting, record_time,"
                    "  event_time, category, topic, text, verification_status)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        case_id,
                        claim.id,
                        claim.version,
                        claim.source_document_id,
                        claim.source_version,
                        claim.source_passage_id,
                        claim.provider_role,
                        claim.observation_setting,
                        claim.record_time,
                        claim.event_time,
                        claim.category,
                        claim.topic,
                        claim.text,
                        claim.verification_status,
                    ),
                )
            for draft in bundle["sections"]:
                import json as _json

                connection.execute(
                    "INSERT INTO sections"
                    " (case_id, template_id, section_id, version, template_version, text,"
                    "  claim_ids, status, review_gate, reviewer, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        case_id,
                        draft.template_id,
                        draft.section_id,
                        draft.version,
                        draft.template_version,
                        draft.text,
                        _json.dumps(draft.claim_ids, ensure_ascii=False),
                        draft.status,
                        draft.review_gate,
                        draft.reviewer,
                        draft.updated_at,
                    ),
                )
        return case_id


class CaseStore:
    """All case-owned reads and writes, structurally bound to one case_id.

    There is deliberately no method that takes a case id: the binding happens
    once in :meth:`SqliteStore.case` after the id is validated and confirmed
    to exist, and every statement below filters on ``self._case_id``.
    """

    def __init__(self, store: SqliteStore, case_id: str) -> None:
        self._store = store
        self._case_id = case_id

    @property
    def case_id(self) -> str:
        return self._case_id

    @property
    def _db(self) -> sqlite3.Connection:
        return self._store._connect()

    # -- materials ------------------------------------------------------

    def list_materials(self) -> list[Material]:
        """Latest version of every material in this case, id-sorted."""
        rows = self._db.execute(
            """
            SELECT m.material_id, m.version, m.title, m.provider, m.date
            FROM materials m
            JOIN (
                SELECT material_id, MAX(version) AS max_version
                FROM materials WHERE case_id = ? GROUP BY material_id
            ) latest ON latest.material_id = m.material_id
                     AND latest.max_version = m.version
            WHERE m.case_id = ?
            ORDER BY m.material_id
            """,
            (self._case_id, self._case_id),
        ).fetchall()
        materials = []
        for row in rows:
            passages = self._db.execute(
                """
                SELECT passage_id, text FROM passages
                WHERE case_id = ? AND material_id = ? AND version = ?
                ORDER BY position
                """,
                (self._case_id, row["material_id"], row["version"]),
            ).fetchall()
            materials.append(
                Material(
                    id=row["material_id"],
                    case_id=self._case_id,
                    version=row["version"],
                    title=row["title"],
                    provider=row["provider"],
                    date=row["date"],
                    passages=[
                        Passage(id=p["passage_id"], text=p["text"]) for p in passages
                    ],
                )
            )
        return materials

    def get_material(self, material_id: str, version: int | None = None) -> Material:
        """One material at an exact version, or the latest when omitted."""
        if version is None:
            row = self._db.execute(
                """
                SELECT MAX(version) AS v FROM materials
                WHERE case_id = ? AND material_id = ?
                """,
                (self._case_id, material_id),
            ).fetchone()
            version = row["v"]
            if version is None:
                raise KeyError(f"unknown material: {material_id}")
        row = self._db.execute(
            """
            SELECT title, provider, date FROM materials
            WHERE case_id = ? AND material_id = ? AND version = ?
            """,
            (self._case_id, material_id, version),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown material: {material_id}")
        passages = self._db.execute(
            """
            SELECT passage_id, text FROM passages
            WHERE case_id = ? AND material_id = ? AND version = ?
            ORDER BY position
            """,
            (self._case_id, material_id, version),
        ).fetchall()
        return Material(
            id=material_id,
            case_id=self._case_id,
            version=version,
            title=row["title"],
            provider=row["provider"],
            date=row["date"],
            passages=[Passage(id=p["passage_id"], text=p["text"]) for p in passages],
        )

    def latest_material_version(self, material_id: str) -> int:
        row = self._db.execute(
            "SELECT MAX(version) AS v FROM materials WHERE case_id = ? AND material_id = ?",
            (self._case_id, material_id),
        ).fetchone()
        return row["v"] or 0

    def import_material(
        self,
        *,
        material_id: str,
        title: str,
        provider: str,
        date: str,
        passages: list[Passage],
    ) -> Material:
        """Append the next immutable version of a material (one transaction)."""
        if not MATERIAL_ID_RE.fullmatch(material_id):
            raise ValueError("material id must be a short anonymous slug")
        material = Material(
            id=material_id,
            case_id=self._case_id,
            version=0,  # replaced below inside the transaction
            title=title,
            provider=provider,
            date=date,
            passages=passages,
        )
        with self._store.transaction() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS v FROM materials WHERE case_id = ? AND material_id = ?",
                (self._case_id, material_id),
            ).fetchone()
            version = (row["v"] or 0) + 1
            material = material.model_copy(update={"version": version})
            connection.execute(
                "INSERT INTO materials (case_id, material_id, version, title, provider, date)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (self._case_id, material_id, version, title, provider, date),
            )
            for position, passage in enumerate(passages, start=1):
                connection.execute(
                    "INSERT INTO passages"
                    " (case_id, material_id, version, passage_id, position, text)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        self._case_id,
                        material_id,
                        version,
                        passage.id,
                        position,
                        passage.text,
                    ),
                )
        return material

    # -- known names ------------------------------------------------------

    def get_known_names(self) -> tuple[str, ...]:
        rows = self._db.execute(
            "SELECT name FROM known_names WHERE case_id = ? ORDER BY name COLLATE NOCASE",
            (self._case_id,),
        ).fetchall()
        return tuple(row[0] for row in rows)

    def set_known_names(self, names: list[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        deduped: list[str] = []
        for name in names:
            name = name.strip()
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                deduped.append(name)
        deduped.sort(key=str.lower)
        with self._store.transaction() as connection:
            connection.execute(
                "DELETE FROM known_names WHERE case_id = ?", (self._case_id,)
            )
            for name in deduped:
                connection.execute(
                    "INSERT INTO known_names (case_id, name) VALUES (?, ?)",
                    (self._case_id, name),
                )
        return tuple(deduped)

    # -- claims -----------------------------------------------------------

    def list_claims(self) -> list[Claim]:
        rows = self._db.execute(
            """
            SELECT c.* FROM claims c
            JOIN (
                SELECT claim_id, MAX(version) AS max_version
                FROM claims WHERE case_id = ? GROUP BY claim_id
            ) latest ON latest.claim_id = c.claim_id
                     AND latest.max_version = c.version
            WHERE c.case_id = ?
            ORDER BY c.claim_id
            """,
            (self._case_id, self._case_id),
        ).fetchall()
        return [self._row_to_claim(row) for row in rows]

    def get_claim(self, claim_id: str) -> Claim:
        row = self._db.execute(
            """
            SELECT * FROM claims
            WHERE case_id = ? AND claim_id = ?
            ORDER BY version DESC LIMIT 1
            """,
            (self._case_id, claim_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"no claim with id {claim_id!r}")
        return self._row_to_claim(row)

    def get_claim_version(self, claim_id: str, version: int) -> Claim:
        row = self._db.execute(
            """
            SELECT * FROM claims
            WHERE case_id = ? AND claim_id = ? AND version = ?
            """,
            (self._case_id, claim_id, version),
        ).fetchone()
        if row is None:
            raise KeyError(f"no claim with id {claim_id!r} at version {version}")
        return self._row_to_claim(row)

    def add_claim(self, *, claim_id: str, **fields) -> Claim:
        with self._store.transaction() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS v FROM claims WHERE case_id = ? AND claim_id = ?",
                (self._case_id, claim_id),
            ).fetchone()
            version = (row["v"] or 0) + 1
            claim = Claim(id=claim_id, case_id=self._case_id, version=version, **fields)
            self._insert_claim(connection, claim)
        return claim

    def mark_claim_status(self, claim_id: str, status: str) -> Claim:
        current = self.get_claim(claim_id)
        with self._store.transaction() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS v FROM claims WHERE case_id = ? AND claim_id = ?",
                (self._case_id, claim_id),
            ).fetchone()
            version = (row["v"] or 0) + 1
            updated = current.model_copy(
                update={"version": version, "verification_status": status}
            )
            self._insert_claim(connection, updated)
        return updated

    def _insert_claim(self, connection: sqlite3.Connection, claim: Claim) -> None:
        connection.execute(
            "INSERT INTO claims"
            " (case_id, claim_id, version, source_document_id, source_version,"
            "  source_passage_id, provider_role, observation_setting, record_time,"
            "  event_time, category, topic, text, verification_status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                claim.case_id,
                claim.id,
                claim.version,
                claim.source_document_id,
                claim.source_version,
                claim.source_passage_id,
                claim.provider_role,
                claim.observation_setting,
                claim.record_time,
                claim.event_time,
                claim.category,
                claim.topic,
                claim.text,
                claim.verification_status,
            ),
        )

    @staticmethod
    def _row_to_claim(row: sqlite3.Row) -> Claim:
        return Claim(
            id=row["claim_id"],
            case_id=row["case_id"],
            version=row["version"],
            source_document_id=row["source_document_id"],
            source_version=row["source_version"],
            source_passage_id=row["source_passage_id"],
            provider_role=row["provider_role"],
            observation_setting=row["observation_setting"],
            record_time=row["record_time"],
            event_time=row["event_time"],
            category=row["category"],
            topic=row["topic"],
            text=row["text"],
            verification_status=row["verification_status"],
        )

    def save_egress_request(self, request) -> None:
        """Insert or replace one egress request row (case-scoped)."""
        import json as _json

        from psychtool.core.egress import EgressRequest

        if not isinstance(request, EgressRequest):
            request = EgressRequest.model_validate(request)
        if request.workspace_id != self._case_id:
            raise ValueError("egress request belongs to a different case")
        with self._store.transaction() as connection:
            connection.execute(
                "INSERT INTO egress_requests"
                " (case_id, request_id, purpose, data_tier, provider_base_url,"
                "  envelope, source_refs, identifier_categories, content_hash, status,"
                "  approval_mode, reviewer, approval_reason, prepared_at, approved_at,"
                "  sent_at, send_lock_owner, transition_lock_owner)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                "         COALESCE((SELECT send_lock_owner FROM egress_requests"
                "                   WHERE case_id = ? AND request_id = ?), NULL),"
                "         COALESCE((SELECT transition_lock_owner FROM egress_requests"
                "                   WHERE case_id = ? AND request_id = ?), NULL))"
                " ON CONFLICT (case_id, request_id) DO UPDATE SET"
                "  purpose = excluded.purpose,"
                "  data_tier = excluded.data_tier,"
                "  provider_base_url = excluded.provider_base_url,"
                "  envelope = excluded.envelope,"
                "  source_refs = excluded.source_refs,"
                "  identifier_categories = excluded.identifier_categories,"
                "  content_hash = excluded.content_hash,"
                "  status = excluded.status,"
                "  approval_mode = excluded.approval_mode,"
                "  reviewer = excluded.reviewer,"
                "  approval_reason = excluded.approval_reason,"
                "  prepared_at = excluded.prepared_at,"
                "  approved_at = excluded.approved_at,"
                "  sent_at = excluded.sent_at",
                (
                    self._case_id,
                    request.request_id,
                    request.purpose,
                    request.data_tier,
                    request.provider_base_url,
                    request.envelope.model_dump_json(),
                    _json.dumps(
                        [ref.model_dump() for ref in request.source_refs],
                        ensure_ascii=False,
                    ),
                    _json.dumps(request.identifier_categories, ensure_ascii=False),
                    request.content_hash,
                    request.status,
                    request.approval_mode,
                    request.reviewer,
                    request.approval_reason,
                    request.prepared_at,
                    request.approved_at,
                    request.sent_at,
                    self._case_id,
                    request.request_id,
                    self._case_id,
                    request.request_id,
                ),
            )

    def get_egress_request(self, request_id: str):
        import json as _json

        from psychtool.core.egress import EgressRequest, OutboundEnvelope, SourceRef

        row = self._db.execute(
            "SELECT * FROM egress_requests WHERE case_id = ? AND request_id = ?",
            (self._case_id, request_id),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"no egress request {request_id!r}")
        return EgressRequest(
            request_id=row["request_id"],
            workspace_id=row["case_id"],
            purpose=row["purpose"],
            data_tier=row["data_tier"],
            provider_base_url=row["provider_base_url"],
            envelope=OutboundEnvelope.model_validate(_json.loads(row["envelope"])),
            source_refs=[
                SourceRef.model_validate(ref) for ref in _json.loads(row["source_refs"])
            ],
            identifier_categories=_json.loads(row["identifier_categories"]),
            content_hash=row["content_hash"],
            status=row["status"],
            approval_mode=row["approval_mode"],
            reviewer=row["reviewer"],
            approval_reason=row["approval_reason"],
            prepared_at=row["prepared_at"],
            approved_at=row["approved_at"],
            sent_at=row["sent_at"],
        )

    def request_lock_key(self, request_id: str) -> str:
        from psychtool.core.egress import _validate_request_id

        request_id = _validate_request_id(request_id)
        return f"sqlite:{self._store.path}:{self._case_id}:{request_id}"

    def _request_exists(self, request_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM egress_requests WHERE case_id = ? AND request_id = ?",
            (self._case_id, request_id),
        ).fetchone()
        return row is not None

    # -- egress locks (in-row owners; fail closed like the JSON lock files) --

    def _lock_update(self, request_id: str, column: str, owner: str | None) -> bool:
        """Conditionally set/clear one lock column; True when the row changed."""
        if column not in ("send_lock_owner", "transition_lock_owner"):
            raise ValueError("unknown lock column")
        # ``column`` is allowlisted above; values stay parameterized.
        if owner is None:
            statement = (
                f"UPDATE egress_requests SET {column} = NULL"
                f" WHERE case_id = ? AND request_id = ? AND {column} = ?"
            )
            parameters = (self._case_id, request_id, owner)
        else:
            statement = (
                f"UPDATE egress_requests SET {column} = ?"
                f" WHERE case_id = ? AND request_id = ? AND {column} IS NULL"
            )
            parameters = (owner, self._case_id, request_id)
        with self._store.transaction() as connection:
            cursor = connection.execute(statement, parameters)
            return cursor.rowcount == 1

    def _lock_release(self, request_id: str, column: str, owner: str) -> None:
        """Clear a lock only when we still own it; mismatch fails closed."""
        if column not in ("send_lock_owner", "transition_lock_owner"):
            raise ValueError("unknown lock column")
        with self._store.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE egress_requests SET {column} = NULL"
                f" WHERE case_id = ? AND request_id = ? AND {column} = ?",
                (self._case_id, request_id, owner),
            )
            if cursor.rowcount == 1:
                return
            row = connection.execute(
                f"SELECT {column} FROM egress_requests"
                " WHERE case_id = ? AND request_id = ?",
                (self._case_id, request_id),
            ).fetchone()
        # Row gone or owner changed: never clear someone else's lock.
        from psychtool.core.egress import EgressStateError

        if row is None or row[0] != owner:
            raise EgressStateError("egress request transition cleanup failed")

    def try_acquire_transition_lock(self, request_id: str, owner: str) -> bool:
        if not self._request_exists(request_id):
            # A missing row must surface as not-found, not as a held lock.
            raise FileNotFoundError(f"no egress request {request_id!r}")
        return self._lock_update(request_id, "transition_lock_owner", owner)

    def release_transition_lock(self, request_id: str, owner: str) -> None:
        self._lock_release(request_id, "transition_lock_owner", owner)

    def try_acquire_send_lock(self, request_id: str, owner: str) -> bool:
        if not self._request_exists(request_id):
            raise FileNotFoundError(f"no egress request {request_id!r}")
        return self._lock_update(request_id, "send_lock_owner", owner)

    def release_send_lock(self, request_id: str, owner: str) -> None:
        # Best-effort like the JSON send lock: never raise on cleanup.
        try:
            self._lock_release(request_id, "send_lock_owner", owner)
        except Exception:
            pass

    # -- sections ---------------------------------------------------------

    def save_section(
        self,
        *,
        template_id: str,
        template_version: int,
        section_id: str,
        text: str,
        claim_ids: list[str],
        status: str,
        review_gate: str,
        reviewer: str | None,
        updated_at: str,
    ) -> SectionDraft:
        import json as _json

        with self._store.transaction() as connection:
            row = connection.execute(
                "SELECT MAX(version) AS v FROM sections"
                " WHERE case_id = ? AND template_id = ? AND section_id = ?",
                (self._case_id, template_id, section_id),
            ).fetchone()
            version = (row["v"] or 0) + 1
            draft = SectionDraft(
                section_id=section_id,
                template_id=template_id,
                template_version=template_version,
                case_id=self._case_id,
                version=version,
                text=text,
                claim_ids=list(dict.fromkeys(claim_ids)),
                status=status,
                review_gate=review_gate,
                reviewer=reviewer,
                updated_at=updated_at,
            )
            connection.execute(
                "INSERT INTO sections"
                " (case_id, template_id, section_id, version, template_version, text,"
                "  claim_ids, status, review_gate, reviewer, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._case_id,
                    template_id,
                    section_id,
                    version,
                    template_version,
                    draft.text,
                    _json.dumps(draft.claim_ids, ensure_ascii=False),
                    status,
                    review_gate,
                    reviewer,
                    updated_at,
                ),
            )
        return draft

    def get_section(self, template_id: str, section_id: str) -> SectionDraft | None:
        import json as _json

        row = self._db.execute(
            """
            SELECT * FROM sections
            WHERE case_id = ? AND template_id = ? AND section_id = ?
            ORDER BY version DESC LIMIT 1
            """,
            (self._case_id, template_id, section_id),
        ).fetchone()
        if row is None:
            return None
        return SectionDraft(
            section_id=row["section_id"],
            template_id=row["template_id"],
            template_version=row["template_version"],
            case_id=row["case_id"],
            version=row["version"],
            text=row["text"],
            claim_ids=_json.loads(row["claim_ids"]),
            status=row["status"],
            review_gate=row["review_gate"],
            reviewer=row["reviewer"],
            updated_at=row["updated_at"],
        )
