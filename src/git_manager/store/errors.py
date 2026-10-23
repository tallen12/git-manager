"""Store errors."""

from pathlib import Path

from git_manager.core.errors import OperationError

LOCKED_HINT = "a daemon is using this data directory; use API mode (--url or --socket)"


class DataDirectoryLockedError(OperationError):
    """Another process holds the data directory, so this one must not write to it.

    Local-mode commands report it as is: the holder is normally the daemon, and API mode
    reaches the same state through it without a second writer.
    """

    def __init__(self, data_dir: Path) -> None:
        super().__init__(f"{LOCKED_HINT} ({data_dir})")
        self.data_dir = data_dir


class SchemaVersionError(Exception):
    """``state.db`` was written by a newer Git Manager than this one."""

    def __init__(self, *, found: int, supported: int) -> None:
        super().__init__(
            f"state.db has schema version {found}, but this Git Manager supports up to "
            f"{supported}; upgrade Git Manager"
        )
        self.found = found
        self.supported = supported
