from pathlib import Path

from git_manager.core import OperationError
from git_manager.store import DataDirectoryLockedError, SchemaVersionError


def test_locked_error_points_to_api_mode() -> None:
    error = DataDirectoryLockedError(Path("data"))

    assert isinstance(error, OperationError)
    assert str(error).startswith(
        "a daemon is using this data directory; use API mode (--url or --socket)"
    )
    assert error.data_dir == Path("data")


def test_schema_version_error_names_both_versions() -> None:
    error = SchemaVersionError(found=3, supported=1)

    assert "version 3" in str(error)
    assert "up to 1" in str(error)
