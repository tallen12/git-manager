"""Schema migrations for ``state.db``, versioned by SQLite's ``user_version``.

Migrations are append-only: never edit a released step, add a new one. Each step runs in
the caller's transaction with the version bump, so a failed step leaves the database as
it was.
"""

from sqlalchemy import Connection, text

from git_manager.store.errors import SchemaVersionError

# MIGRATIONS[n] takes the schema from version n to n + 1.
MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """
        CREATE TABLE branches (
            id VARCHAR NOT NULL PRIMARY KEY,
            name VARCHAR NOT NULL UNIQUE,
            data VARCHAR NOT NULL
        )
        """,
        """
        CREATE TABLE runs (
            seq INTEGER NOT NULL PRIMARY KEY,
            id VARCHAR NOT NULL UNIQUE,
            branch_id VARCHAR NOT NULL,
            started_at_us INTEGER NOT NULL,
            data VARCHAR NOT NULL
        )
        """,
        "CREATE INDEX ix_runs_branch_id ON runs (branch_id)",
        """
        CREATE TABLE events (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            data VARCHAR NOT NULL
        )
        """,
    ),
)

LATEST_VERSION = len(MIGRATIONS)


def schema_version(connection: Connection) -> int:
    """Return the schema version of the open database (0 when it is new)."""
    version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
    if not isinstance(version, int):
        msg = f"PRAGMA user_version returned {version!r}"
        raise TypeError(msg)
    return version


def migrate(connection: Connection, *, migrations: tuple[tuple[str, ...], ...] = MIGRATIONS) -> int:
    """Apply the steps the database has not seen yet and return the new version.

    Raises ``SchemaVersionError`` for a database newer than ``migrations``.
    """
    current = schema_version(connection)
    if current > len(migrations):
        raise SchemaVersionError(found=current, supported=len(migrations))
    for statements in migrations[current:]:
        for statement in statements:
            connection.execute(text(statement))
    # PRAGMA takes no bound parameters; the value is our own int.
    connection.exec_driver_sql(f"PRAGMA user_version = {len(migrations)}")
    return len(migrations)
