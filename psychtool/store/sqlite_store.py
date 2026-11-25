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

import hashlib
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from psychtool.core.categorize import (
    CATEGORY_KEYS,
    ROLE_KEYS,
    CategorizeRules,
    default_rules,
    suggest_category,
    suggest_role,
)
from psychtool.core.claims import Claim
from psychtool.core.extract import Extractor, extract_evidence
from psychtool.core.sections import SectionDraft
from psychtool.core.workspace import Material, Passage
from psychtool.store import audit as _audit

# Mirrors the server-side case-id rule: no path separators, no SQL/LIKE
# metacharacters, bounded length. Validated before any SQL runs.
CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Mirrors the material-id rule used by the ingest path.
MATERIAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_SCHEMA_VERSION = 5

# R5 (ADR 0015): when SHE chose the category/role, the effective reason is a
# fixed sentence about her choice — never the rule's keyword sentence, which
# would be misleading next to her chip. The rule's reason stays available on
# the suggested_*_reason fields.
CLINICIAN_CATEGORY_REASON = "You chose this category."
CLINICIAN_ROLE_REASON = "You chose this source role."

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS cases (
        case_id                TEXT PRIMARY KEY CHECK (length(case_id) BETWEEN 1 AND 64),
        data_tier              TEXT NOT NULL CHECK (data_tier IN ('synthetic', 'real')),
        created_at             TEXT NOT NULL,
        synthetic_confirmed_at TEXT
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
            CHECK (status IN ('prepared', 'approved', 'sent', 'invalidated',
                              'send_interrupted')),
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
    # Audit log (ADR 0011): append-only, hash-chained, structurally unable to
    # hold free text. The triggers below block UPDATE/DELETE on the app path.
    # item_count (schema v4, ADR 0013) is an integer-only optional count.
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        seq          INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id      TEXT,
        ts           TEXT NOT NULL,
        action       TEXT NOT NULL,
        object_type  TEXT NOT NULL,
        object_id    TEXT NOT NULL,
        content_hash TEXT,
        destination  TEXT,
        prev_hash    TEXT NOT NULL,
        entry_hash   TEXT NOT NULL,
        item_count   INTEGER CHECK (item_count IS NULL OR item_count >= 0)
    )
    """,
    # Persisted evidence (PT-07 / ADR 0015, schema v5). The id is location-
    # derived (sha256 of case/material/version/passage/start/end), so her
    # category/role choices survive rule changes that keep the same span;
    # rules updates refresh only the suggested_* columns. Rows are superseded,
    # never deleted; a superseded row with a correction stays visible.
    """
    CREATE TABLE IF NOT EXISTS evidence (
        case_id            TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
        evidence_id        TEXT NOT NULL,
        material_id        TEXT NOT NULL,
        material_version   INTEGER NOT NULL CHECK (material_version >= 1),
        passage_id         TEXT NOT NULL,
        start              INTEGER NOT NULL CHECK (start >= 0),
        end                INTEGER NOT NULL CHECK (end > start),
        quote              TEXT NOT NULL,
        suggested_category TEXT NOT NULL
            CHECK (suggested_category IN ('family_history', 'medical_history',
                                          'test_results', 'behavioral_observations',
                                          'development_school', 'daily_living',
                                          'other', 'uncategorized')),
        category_reason    TEXT NOT NULL,
        suggested_role     TEXT NOT NULL
            CHECK (suggested_role IN ('school', 'caregiver', 'medical_record',
                                      'clinician', 'client', 'to_confirm')),
        role_reason        TEXT NOT NULL,
        category           TEXT
            CHECK (category IS NULL OR category IN ('family_history', 'medical_history',
                                                    'test_results', 'behavioral_observations',
                                                    'development_school', 'daily_living',
                                                    'other', 'uncategorized')),
        role               TEXT
            CHECK (role IS NULL OR role IN ('school', 'caregiver', 'medical_record',
                                            'clinician', 'client', 'to_confirm')),
        status             TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
        rules_version      TEXT NOT NULL,
        PRIMARY KEY (case_id, evidence_id),
        FOREIGN KEY (case_id, material_id, material_version, passage_id)
            REFERENCES passages(case_id, material_id, version, passage_id)
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_update
    BEFORE UPDATE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit log is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit log is append-only');
    END
    """,
)

# Schema v1 -> v2 (ADR 0011): add the append-only, hash-chained audit log,
# and rebuild ``egress_requests`` because SQLite cannot alter a CHECK
# constraint and the v2 status set adds ``send_interrupted``. The rebuild
# follows the SQLite "12 steps" procedure for schema changes: the migration
# transaction runs with ``PRAGMA defer_foreign_keys=ON`` (a PRAGMA that works
# inside a transaction), the rows are copied into a new table, the old table
# is dropped, the new one is renamed, and ``PRAGMA foreign_key_check``
# verifies no reference broke before commit. A v1 database from PT-02 opens
# fine and gains the table plus triggers.
_MIGRATION_STATEMENTS = {
    2: (
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            seq          INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id      TEXT,
            ts           TEXT NOT NULL,
            action       TEXT NOT NULL,
            object_type  TEXT NOT NULL,
            object_id    TEXT NOT NULL,
            content_hash TEXT,
            destination  TEXT,
            prev_hash    TEXT NOT NULL,
            entry_hash   TEXT NOT NULL
        )
        """,
        """
        CREATE TRIGGER IF NOT EXISTS audit_log_no_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit log is append-only');
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit log is append-only');
        END
        """,
        """
        CREATE TABLE egress_requests_v2 (
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
                CHECK (status IN ('prepared', 'approved', 'sent', 'invalidated',
                                  'send_interrupted')),
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
        """
        INSERT INTO egress_requests_v2
            (case_id, request_id, purpose, data_tier, provider_base_url,
             envelope, source_refs, identifier_categories, content_hash, status,
             approval_mode, reviewer, approval_reason, prepared_at, approved_at,
             sent_at, send_lock_owner, transition_lock_owner)
        SELECT case_id, request_id, purpose, data_tier, provider_base_url,
               envelope, source_refs, identifier_categories, content_hash, status,
               approval_mode, reviewer, approval_reason, prepared_at, approved_at,
               sent_at, send_lock_owner, transition_lock_owner
        FROM egress_requests
        """,
        "DROP TABLE egress_requests",
        "ALTER TABLE egress_requests_v2 RENAME TO egress_requests",
    ),
    # Schema v2 -> v3 (ADR 0012): remember the R2-AC3 first-upload
    # confirmation per case. NULL means "not yet confirmed"; confirming is a
    # one-way set-once write in the same transaction as its audit row.
    3: (
        "ALTER TABLE cases ADD COLUMN synthetic_confirmed_at TEXT",
    ),
    # Schema v3 -> v4 (ADR 0013): the audit log gains an optional integer
    # item_count (used by material.protected_blocked). Existing rows keep
    # NULL, and the chain hash covers item_count only when it is not NULL, so
    # pre-v4 rows verify exactly as before.
    4: (
        "ALTER TABLE audit_log ADD COLUMN item_count INTEGER"
        " CHECK (item_count IS NULL OR item_count >= 0)",
    ),
    # Schema v4 -> v5 (PT-07 / ADR 0015): persisted evidence rows with stable,
    # location-derived ids. Pure additive migration: existing tables and the
    # audit chain are untouched.
    5: (
        """
        CREATE TABLE IF NOT EXISTS evidence (
            case_id            TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
            evidence_id        TEXT NOT NULL,
            material_id        TEXT NOT NULL,
            material_version   INTEGER NOT NULL CHECK (material_version >= 1),
            passage_id         TEXT NOT NULL,
            start              INTEGER NOT NULL CHECK (start >= 0),
            end                INTEGER NOT NULL CHECK (end > start),
            quote              TEXT NOT NULL,
            suggested_category TEXT NOT NULL
                CHECK (suggested_category IN ('family_history', 'medical_history',
                                              'test_results', 'behavioral_observations',
                                              'development_school', 'daily_living',
                                              'other', 'uncategorized')),
            category_reason    TEXT NOT NULL,
            suggested_role     TEXT NOT NULL
                CHECK (suggested_role IN ('school', 'caregiver', 'medical_record',
                                          'clinician', 'client', 'to_confirm')),
            role_reason        TEXT NOT NULL,
            category           TEXT
                CHECK (category IS NULL OR category IN ('family_history', 'medical_history',
                                                        'test_results', 'behavioral_observations',
                                                        'development_school', 'daily_living',
                                                        'other', 'uncategorized')),
            role               TEXT
                CHECK (role IS NULL OR role IN ('school', 'caregiver', 'medical_record',
                                                'clinician', 'client', 'to_confirm')),
            status             TEXT NOT NULL CHECK (status IN ('active', 'superseded')),
            rules_version      TEXT NOT NULL,
            PRIMARY KEY (case_id, evidence_id),
            FOREIGN KEY (case_id, material_id, material_version, passage_id)
                REFERENCES passages(case_id, material_id, version, passage_id)
        )
        """,
    ),
}


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
            if not 0 < version < _SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported database schema version: {version}"
                )
            for step in range(version + 1, _SCHEMA_VERSION + 1):
                with self.transaction() as transaction:
                    # Table rebuilds must not trip foreign-key enforcement
                    # mid-copy; defer_foreign_keys is the PRAGMA that can be
                    # set inside an open transaction (SQLite schema-change
                    # procedure). foreign_key_check verifies nothing broke.
                    transaction.execute("PRAGMA defer_foreign_keys=ON")
                    for statement in _MIGRATION_STATEMENTS[step]:
                        transaction.execute(statement)
                    broken = transaction.execute("PRAGMA foreign_key_check").fetchall()
                    if broken:
                        raise RuntimeError(
                            f"migration to schema v{step} broke foreign keys: {broken}"
                        )
                    transaction.execute(f"PRAGMA user_version={step}")

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
                self.append_audit(
                    case_id=case_id,
                    action="case.create",
                    object_type="case",
                    object_id=case_id,
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

    # -- audit log (ADR 0011) ----------------------------------------------

    def append_audit(
        self,
        *,
        case_id: str | None,
        action: str,
        object_type: str,
        object_id: str,
        content_hash: str | None = None,
        destination: str | None = None,
        item_count: int | None = None,
    ) -> None:
        """Append one chained audit row (joins an open transaction)."""
        _audit.append_audit(
            self._connect(),
            case_id=case_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            content_hash=content_hash,
            destination=destination,
            item_count=item_count,
        )

    def verify_audit_chain(self) -> tuple[bool, int, int | None]:
        return _audit.verify_audit_chain(self)

    def list_audit_entries(self) -> list[sqlite3.Row]:
        """All audit rows in chain order (used by verification and tests)."""
        return self._connect().execute(
            "SELECT * FROM audit_log ORDER BY seq"
        ).fetchall()

    # -- JSON import ----------------------------------------------------

    def import_workspace(self, workspace: Path | str) -> str:
        """Load an ADR 0005 JSON workspace directory as one transaction.

        All or nothing: any failure rolls every inserted row back. Refuses to
        import over an existing case id. Returns the imported case id.

        R13 (ADR 0013): passages matching the protected-content screen are
        dropped before any row is written; a material whose passages are all
        blocked is not imported at all, and one
        ``material.protected_blocked`` audit row per affected material is
        written inside the same transaction (count + hash only). The CLI's
        own JSON storage is not changed by this screen.
        """
        from psychtool.core.protected import find_protected
        from psychtool.store.importer import read_json_workspace

        bundle = read_json_workspace(Path(workspace))
        case_id = bundle["case_id"]
        validate_case_id(case_id)
        if self.case_exists(case_id):
            raise CaseExistsError(f"case already exists: {case_id}")
        # Screen everything before the transaction opens: a checker failure
        # aborts the import with nothing written (fail-closed).
        screened: list[tuple[Material, list[Passage], int, str | None]] = []
        # Passage ids that were blocked per material id — claims citing any of
        # them are rejected below (their source would no longer exist).
        blocked_passage_ids: dict[str, set[str]] = {}
        for material in bundle["materials"]:
            try:
                blocked_indexes = find_protected(
                    [passage.text for passage in material.passages]
                )
            except Exception:
                raise ValueError(
                    "protected-content check failed; import rejected"
                ) from None
            if not blocked_indexes:
                screened.append((material, list(material.passages), 0, None))
                continue
            blocked = set(blocked_indexes)
            blocked_passage_ids[material.id] = {
                material.passages[i].id for i in blocked_indexes
            }
            # Keep ORIGINAL passage ids: claims cite passages by id, so
            # renumbering would silently re-point claims at other passages.
            # Only the stored ``position`` stays sequential.
            kept = [
                passage
                for i, passage in enumerate(material.passages)
                if i not in blocked
            ]
            blocked_hash = hashlib.sha256(
                "\n\n".join(material.passages[i].text for i in blocked_indexes).encode("utf-8")
            ).hexdigest()
            screened.append((material, kept, len(blocked_indexes), blocked_hash))
        # Claims fail closed: a claim whose own text trips the screen, or that
        # cites a blocked passage, rejects the whole import — nothing written.
        from psychtool.core.protected import is_protected

        try:
            for claim in bundle["claims"]:
                if is_protected(claim.text):
                    raise ValueError(
                        "protected content in workspace claims; import rejected"
                    )
                if claim.source_passage_id in blocked_passage_ids.get(
                    claim.source_document_id, set()
                ):
                    raise ValueError(
                        "protected content in workspace claims; import rejected"
                    )
        except ValueError:
            raise
        except Exception:
            raise ValueError(
                "protected-content check failed; import rejected"
            ) from None
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
            self.append_audit(
                case_id=case_id,
                action="case.import_json",
                object_type="case",
                object_id=case_id,
            )
            for material, passages, blocked_count, blocked_hash in screened:
                if not passages:
                    # Every passage was blocked: no material row at all, only
                    # the block audit row (count + hash, never text).
                    if blocked_count:
                        self.append_audit(
                            case_id=case_id,
                            action="material.protected_blocked",
                            object_type="material",
                            object_id=material.id,
                            content_hash=blocked_hash,
                            item_count=blocked_count,
                        )
                    continue
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
                for position, passage in enumerate(passages, start=1):
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
                if blocked_count:
                    self.append_audit(
                        case_id=case_id,
                        action="material.protected_blocked",
                        object_type="material",
                        object_id=material.id,
                        content_hash=blocked_hash,
                        item_count=blocked_count,
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
        # Transport the server is about to use for a ``sent`` transition;
        # the send route sets this before calling send_approved so the audit
        # row for ``egress.send`` can record it. Allowlist-validated on use.
        self.audit_destination: str | None = None

    @property
    def case_id(self) -> str:
        return self._case_id

    @property
    def _db(self) -> sqlite3.Connection:
        return self._store._connect()

    # -- synthetic-materials confirmation (R2-AC3, ADR 0012) ---------------

    def is_synthetic_confirmed(self) -> bool:
        """True once this case's first-upload confirmation was recorded."""
        row = self._db.execute(
            "SELECT synthetic_confirmed_at FROM cases WHERE case_id = ?",
            (self._case_id,),
        ).fetchone()
        return row is not None and row["synthetic_confirmed_at"] is not None

    def confirm_synthetic(self) -> bool:
        """Record the first-upload confirmation, set-once and idempotent.

        Returns True only when this call changed the case. The
        ``case.confirm_synthetic`` audit row is appended in the *same*
        transaction (ADR 0011), so a crash or an audit failure can never leave
        a confirmation without its audit row; repeated confirmations append
        no extra rows.
        """
        with self._store.transaction() as connection:
            cursor = connection.execute(
                "UPDATE cases SET synthetic_confirmed_at = ?"
                " WHERE case_id = ? AND synthetic_confirmed_at IS NULL",
                (_utcnow(), self._case_id),
            )
            changed = cursor.rowcount == 1
            if changed:
                self.append_audit(
                    case_id=self._case_id,
                    action="case.confirm_synthetic",
                    object_type="case",
                    object_id=self._case_id,
                )
            return changed

    def append_audit(
        self,
        *,
        case_id: str | None,
        action: str,
        object_type: str,
        object_id: str,
        content_hash: str | None = None,
        destination: str | None = None,
        item_count: int | None = None,
    ) -> None:
        """Append one audit row through the underlying store connection."""
        self._store.append_audit(
            case_id=case_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            content_hash=content_hash,
            destination=destination,
            item_count=item_count,
        )

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
        blocked_count: int = 0,
        blocked_hash: str | None = None,
    ) -> Material:
        """Append the next immutable version of a material (one transaction).

        When the R13 screen (ADR 0013) dropped protected passages before this
        call, ``blocked_count``/``blocked_hash`` describe them and a
        ``material.protected_blocked`` row is written in the *same*
        transaction as the material import (ADR 0011 rule).
        """
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
            # The audit row commits with the material it describes: content
            # hash only, never title/provider/date/passage text.
            self.append_audit(
                case_id=self._case_id,
                action="material.import",
                object_type="material",
                object_id=material_id,
                content_hash=hashlib.sha256(
                    "\n\n".join(p.text for p in passages).encode("utf-8")
                ).hexdigest(),
            )
            if blocked_count:
                # R13 (ADR 0013): the block row rides the same transaction as
                # the import it qualifies; count + hash only, never text.
                self.append_audit(
                    case_id=self._case_id,
                    action="material.protected_blocked",
                    object_type="material",
                    object_id=material_id,
                    content_hash=blocked_hash,
                    item_count=blocked_count,
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
            # The audit row commits with the claim it describes: text hash
            # only, never claim text.
            self.append_audit(
                case_id=self._case_id,
                action="claim.accept",
                object_type="claim",
                object_id=claim.id,
                content_hash=hashlib.sha256(claim.text.encode("utf-8")).hexdigest(),
            )
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

    # -- evidence (PT-07 / ADR 0015) ----------------------------------------

    @staticmethod
    def _evidence_id(
        case_id: str,
        material_id: str,
        material_version: int,
        passage_id: str,
        start: int,
        end: int,
    ) -> str:
        """Stable id derived from the location only (never rules/category)."""
        payload = "\x1f".join(
            (case_id, material_id, str(material_version), passage_id, str(start), str(end))
        )
        return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def refresh_evidence(
        self,
        extractor: Extractor,
        rules: CategorizeRules | None = None,
        material_ids: set[str] | None = None,
    ) -> dict[str, int]:
        """Recompute persisted evidence for the latest material versions.

        One transaction, idempotent: rows are upserted by their stable id —
        existing rows get new suggestions/reasons/rules_version but her
        ``category``/``role`` choices are NEVER overwritten; rows the current
        rules no longer produce become ``superseded`` (never deleted). One
        ``evidence.extract`` audit row is written per material whose rows
        changed (item_count = its active items). Returns per-material active
        counts plus the number of candidates dropped by the span check.

        ``material_ids`` restricts the refresh to those materials (upload /
        paste refresh only the imported material); ``None`` refreshes every
        material of the case.
        """
        rules = rules or default_rules()
        materials = [
            material
            for material in self.list_materials()
            if material_ids is None or material.id in material_ids
        ]
        result = extract_evidence(extractor, materials)
        by_material: dict[str, list] = {material.id: [] for material in materials}
        for item in result.items:
            by_material.setdefault(item.span.material_id, []).append(item)
        counts: dict[str, int] = {}
        with self._store.transaction() as connection:
            for material_id in sorted(by_material):
                # Preload every existing row of this material in ONE query;
                # the per-candidate loop below is then pure dict lookups.
                existing_rows = {
                    row["evidence_id"]: row
                    for row in connection.execute(
                        "SELECT evidence_id, category, role, suggested_category,"
                        "       category_reason, suggested_role, role_reason,"
                        "       rules_version, status"
                        " FROM evidence WHERE case_id = ? AND material_id = ?",
                        (self._case_id, material_id),
                    ).fetchall()
                }
                active = 0
                changed = False
                produced_ids: set[str] = set()
                for item in by_material[material_id]:
                    span = item.span
                    evidence_id = self._evidence_id(
                        self._case_id,
                        span.material_id,
                        span.material_version,
                        span.passage_id,
                        span.start,
                        span.end,
                    )
                    produced_ids.add(evidence_id)
                    suggested_category, _, category_reason = suggest_category(
                        item.quote, rules
                    )
                    suggested_role, _, role_reason = suggest_role(item.quote, rules)
                    existing = existing_rows.get(evidence_id)
                    if existing is None:
                        connection.execute(
                            "INSERT INTO evidence"
                            " (case_id, evidence_id, material_id, material_version,"
                            "  passage_id, start, end, quote, suggested_category,"
                            "  category_reason, suggested_role, role_reason, category,"
                            "  role, status, rules_version)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,"
                            "         'active', ?)",
                            (
                                self._case_id,
                                evidence_id,
                                span.material_id,
                                span.material_version,
                                span.passage_id,
                                span.start,
                                span.end,
                                item.quote,
                                suggested_category,
                                category_reason,
                                suggested_role,
                                role_reason,
                                rules.version,
                            ),
                        )
                        changed = True
                    else:
                        updates: dict[str, object] = {}
                        if existing["suggested_category"] != suggested_category:
                            updates["suggested_category"] = suggested_category
                        if existing["category_reason"] != category_reason:
                            updates["category_reason"] = category_reason
                        if existing["suggested_role"] != suggested_role:
                            updates["suggested_role"] = suggested_role
                        if existing["role_reason"] != role_reason:
                            updates["role_reason"] = role_reason
                        if existing["rules_version"] != rules.version:
                            updates["rules_version"] = rules.version
                        if existing["status"] != "active":
                            updates["status"] = "active"
                        if updates:
                            assignments = ", ".join(f"{key} = ?" for key in updates)
                            connection.execute(
                                f"UPDATE evidence SET {assignments}"
                                " WHERE case_id = ? AND evidence_id = ?",
                                (*updates.values(), self._case_id, evidence_id),
                            )
                            changed = True
                    active += 1
                # Rows this material no longer produces become superseded —
                # never deleted, so a correction on them survives (R5/ADR 0015).
                # This covers both spans the current rules dropped and rows
                # left over from an older material version.
                for row in existing_rows.values():
                    if row["status"] != "active" or row["evidence_id"] in produced_ids:
                        continue
                    connection.execute(
                        "UPDATE evidence SET status = 'superseded'"
                        " WHERE case_id = ? AND evidence_id = ?",
                        (self._case_id, row["evidence_id"]),
                    )
                    changed = True
                counts[material_id] = active
                if changed:
                    self.append_audit(
                        case_id=self._case_id,
                        action="evidence.extract",
                        object_type="material",
                        object_id=material_id,
                        item_count=active,
                    )
        return {"materials": counts, "dropped": result.dropped}

    def list_evidence(self) -> list[dict]:
        """Active evidence rows plus superseded rows that carry a correction.

        Read-only. The effective category/role is her choice when set,
        otherwise the current suggestion; ``category_set_by``/``role_set_by``
        say which. When SHE chose, the effective reason is the fixed
        "You chose ..." sentence and the rule's reason stays available as
        ``suggested_*_reason`` (so the UI never shows a rule reason next to
        her chip). Superseded corrected rows are flagged
        ``kept_because_corrected`` so the UI can show why they remain.
        ``paragraph`` comes from a JOIN on passages (no per-item query) and
        the ordering follows passage position, not the passage id string.
        """
        rows = self._db.execute(
            """
            SELECT e.*, m.title AS material_title, p.position AS paragraph
            FROM evidence e
            JOIN materials m
              ON m.case_id = e.case_id AND m.material_id = e.material_id
             AND m.version = e.material_version
            LEFT JOIN passages p
              ON p.case_id = e.case_id AND p.material_id = e.material_id
             AND p.version = e.material_version AND p.passage_id = e.passage_id
            WHERE e.case_id = ?
              AND (e.status = 'active' OR e.category IS NOT NULL OR e.role IS NOT NULL)
            ORDER BY e.material_id, e.material_version, p.position, e.start, e.evidence_id
            """,
            (self._case_id,),
        ).fetchall()
        items = []
        for row in rows:
            superseded = row["status"] == "superseded"
            category_set_by = "clinician" if row["category"] else "suggestion"
            role_set_by = "clinician" if row["role"] else "suggestion"
            items.append(
                {
                    "id": row["evidence_id"],
                    "quote": row["quote"],
                    "material_id": row["material_id"],
                    "material_title": row["material_title"],
                    "material_version": row["material_version"],
                    "passage_id": row["passage_id"],
                    "paragraph": row["paragraph"] or 0,
                    "start": row["start"],
                    "end": row["end"],
                    "category": row["category"] or row["suggested_category"],
                    "category_reason": (
                        CLINICIAN_CATEGORY_REASON
                        if category_set_by == "clinician"
                        else row["category_reason"]
                    ),
                    "category_set_by": category_set_by,
                    "suggested_category": row["suggested_category"],
                    "suggested_category_reason": row["category_reason"],
                    "role": row["role"] or row["suggested_role"],
                    "role_reason": (
                        CLINICIAN_ROLE_REASON
                        if role_set_by == "clinician"
                        else row["role_reason"]
                    ),
                    "role_set_by": role_set_by,
                    "suggested_role": row["suggested_role"],
                    "suggested_role_reason": row["role_reason"],
                    "kept_because_corrected": superseded,
                }
            )
        return items

    def evidence_needs_extraction(self) -> bool:
        """True when any latest material version has no evidence rows yet."""
        row = self._db.execute(
            """
            SELECT 1 FROM materials m
            JOIN (
                SELECT material_id, MAX(version) AS max_version
                FROM materials WHERE case_id = ? GROUP BY material_id
            ) latest ON latest.material_id = m.material_id
                     AND latest.max_version = m.version
            WHERE m.case_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM evidence e
                  WHERE e.case_id = m.case_id AND e.material_id = m.material_id
                    AND e.material_version = m.version
              )
            LIMIT 1
            """,
            (self._case_id, self._case_id),
        ).fetchone()
        return row is not None

    def get_evidence(self, evidence_id: str) -> dict:
        row = self._db.execute(
            "SELECT * FROM evidence WHERE case_id = ? AND evidence_id = ?",
            (self._case_id, evidence_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown evidence: {evidence_id}")
        return dict(row)

    def set_evidence_choice(
        self,
        evidence_id: str,
        *,
        category: str | None = None,
        role: str | None = None,
        set_category: bool = False,
        set_role: bool = False,
    ) -> dict:
        """Record her category/role choice (or reset it with None).

        ``set_category``/``set_role`` distinguish "not provided" from an
        explicit null reset. One transaction per call with one audit row
        (``evidence.categorize`` / ``evidence.set_role``; ids only, no text).
        Unknown id raises KeyError; a non-allowlisted key raises ValueError.
        """
        if set_category and category is not None and category not in CATEGORY_KEYS:
            raise ValueError("category is not on the allowlist")
        if set_role and role is not None and role not in ROLE_KEYS:
            raise ValueError("role is not on the allowlist")
        self.get_evidence(evidence_id)  # unknown id -> KeyError before any write
        with self._store.transaction() as connection:
            current = self.get_evidence(evidence_id)
            if set_category and current["category"] != category:
                connection.execute(
                    "UPDATE evidence SET category = ?"
                    " WHERE case_id = ? AND evidence_id = ?",
                    (category, self._case_id, evidence_id),
                )
                self.append_audit(
                    case_id=self._case_id,
                    action="evidence.categorize",
                    object_type="evidence",
                    object_id=evidence_id,
                )
            if set_role and current["role"] != role:
                connection.execute(
                    "UPDATE evidence SET role = ?"
                    " WHERE case_id = ? AND evidence_id = ?",
                    (role, self._case_id, evidence_id),
                )
                self.append_audit(
                    case_id=self._case_id,
                    action="evidence.set_role",
                    object_type="evidence",
                    object_id=evidence_id,
                )
        return self.get_evidence(evidence_id)

    # Status transitions that must leave exactly one audit row in the same
    # transaction as the state change itself (ADR 0011).
    _EGRESS_AUDIT_ACTIONS = {
        "prepared": "egress.prepare",
        "approved": "egress.approve",
        "invalidated": "egress.invalidate",
        "sent": "egress.send",
    }

    def save_egress_request(self, request) -> None:
        """Insert or replace one egress request row (case-scoped).

        When the status changes to ``prepared``, ``approved``, ``invalidated``
        or ``sent``, the matching audit row is appended in the *same*
        transaction, so a crash or an audit failure can never leave a state
        change without its audit entry (the write rolls back instead). For
        ``sent`` the destination is taken from :attr:`audit_destination`,
        which the server sets to the transport it is about to use.
        """
        import json as _json

        from psychtool.core.egress import EgressRequest

        if not isinstance(request, EgressRequest):
            request = EgressRequest.model_validate(request)
        if request.workspace_id != self._case_id:
            raise ValueError("egress request belongs to a different case")
        with self._store.transaction() as connection:
            previous = connection.execute(
                "SELECT status FROM egress_requests WHERE case_id = ? AND request_id = ?",
                (self._case_id, request.request_id),
            ).fetchone()
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
            previous_status = previous["status"] if previous is not None else None
            action = (
                self._EGRESS_AUDIT_ACTIONS.get(request.status)
                if request.status != previous_status
                else None
            )
            if action is not None:
                self.append_audit(
                    case_id=self._case_id,
                    action=action,
                    object_type="egress_request",
                    object_id=request.request_id,
                    content_hash=request.content_hash,
                    destination=(
                        self.audit_destination if request.status == "sent" else None
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
            self.append_audit(
                case_id=self._case_id,
                action="section.save",
                object_type="section",
                object_id=section_id,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
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
