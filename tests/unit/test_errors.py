import subprocess
import sys
from pathlib import Path

import pytest

import git_manager
from git_manager.errors import ConflictError, NotFoundError, OperationError, UnavailableError

PACKAGES = sorted(
    path.name
    for path in Path(git_manager.__file__).parent.iterdir()
    if (path / "__init__.py").is_file()
)


def test_not_found_names_the_record() -> None:
    error = NotFoundError(kind="branch", key="feature/x")

    assert str(error) == "branch not found: feature/x"
    assert (error.kind, error.key) == ("branch", "feature/x")


def test_unavailable_gives_the_reason() -> None:
    error = UnavailableError("sync", reason="not in the REST API yet")

    assert str(error) == "sync is not available: not in the REST API yet"


def test_every_operation_error_shares_one_base() -> None:
    errors = [
        NotFoundError(kind="run", key="r"),
        ConflictError("tracked"),
        UnavailableError("x", reason="y"),
    ]

    assert all(isinstance(error, OperationError) for error in errors)


@pytest.mark.parametrize("package", PACKAGES)
def test_every_package_imports_on_its_own(package: str) -> None:
    # A fresh interpreter, so modules other tests already imported cannot hide a cycle;
    # raising these errors from a domain must never require loading ``git_manager.core``.
    result = subprocess.run(
        [sys.executable, "-c", f"import git_manager.{package}"],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
