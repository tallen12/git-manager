from git_manager.core import ConflictError, NotFoundError, OperationError, UnavailableError


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
