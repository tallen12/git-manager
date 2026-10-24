"""SQLite persistence behind one repository protocol per record type."""

from git_manager.store.database import (
    Database,
    open_database,
    open_memory_database,
    state_db_path,
)
from git_manager.store.errors import DataDirectoryLockedError, SchemaVersionError
from git_manager.store.lock import FileDataDirectoryLock, held
from git_manager.store.protocols import (
    BranchRepository,
    DataDirectoryLock,
    EventRepository,
    RunRepository,
)
from git_manager.store.repositories import (
    SqlBranchRepository,
    SqlEventRepository,
    SqlRunRepository,
)

__all__ = [
    "BranchRepository",
    "DataDirectoryLock",
    "DataDirectoryLockedError",
    "Database",
    "EventRepository",
    "FileDataDirectoryLock",
    "RunRepository",
    "SchemaVersionError",
    "SqlBranchRepository",
    "SqlEventRepository",
    "SqlRunRepository",
    "held",
    "open_database",
    "open_memory_database",
    "state_db_path",
]
