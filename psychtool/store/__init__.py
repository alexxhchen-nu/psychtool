"""Local case storage backends.

The browser/server path persists everything in one SQLite file (ADR 0010).
The legacy CLI/TUI path still uses JSON workspace directories (ADR 0005).
"""

from psychtool.store.sqlite_store import (  # noqa: F401
    CaseExistsError,
    CaseStore,
    SqliteStore,
    default_db_path,
)
