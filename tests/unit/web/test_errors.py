import httpx
import pytest
from fastapi import FastAPI

from git_manager.branches import BranchState
from git_manager.config import ConfigError
from git_manager.errors import ConflictError, NotFoundError, OperationError, UnavailableError
from git_manager.rebasing.errors import BranchOnHoldError
from git_manager.web.errors import (
    ConflictBody,
    ErrorBody,
    ErrorResponse,
    FailedBody,
    InvalidConfigBody,
    NotFoundBody,
    UnavailableBody,
    add_error_handlers,
    from_response,
    to_response,
)

ERRORS: list[tuple[OperationError, int, ErrorBody]] = [
    (NotFoundError(kind="branch", key="f"), 404, NotFoundBody(kind="branch", key="f")),
    (ConflictError("already tracked"), 409, ConflictBody()),
    (
        UnavailableError("watch", reason="later"),
        501,
        UnavailableBody(operation="watch", reason="later"),
    ),
    (
        ConfigError("c.yaml", ["repo.url: missing", "verify.test: empty"]),
        422,
        InvalidConfigBody(source="c.yaml", problems=("repo.url: missing", "verify.test: empty")),
    ),
    (OperationError("something else"), 400, FailedBody()),
]


@pytest.mark.parametrize(("error", "code", "body"), ERRORS)
def test_each_error_maps_to_its_status_and_body(
    error: OperationError, code: int, body: ErrorBody
) -> None:
    assert to_response(error) == (code, ErrorResponse(detail=str(error), error=body))


@pytest.mark.parametrize(("error", "code", "body"), ERRORS)
def test_the_body_maps_back_to_the_same_error(
    error: OperationError, code: int, body: ErrorBody
) -> None:
    _, response = to_response(error)
    wire = ErrorResponse.model_validate_json(response.model_dump_json())

    rebuilt = from_response(wire)

    assert type(rebuilt) is type(error)
    assert str(rebuilt) == str(error)


def test_a_subclass_maps_like_its_parent_with_its_own_message() -> None:
    error = BranchOnHoldError(branch="f", state=BranchState.PAUSED)

    code, response = to_response(error)
    rebuilt = from_response(response)

    assert code == 409
    assert isinstance(rebuilt, ConflictError)
    assert str(rebuilt) == "cannot run f: it is paused"


async def test_handlers_answer_operation_errors_and_leave_others_alone() -> None:
    app = FastAPI()
    add_error_handlers(app)

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError(kind="run", key="r")

    @app.get("/broken")
    async def broken() -> None:
        msg = "a bug"
        raise RuntimeError(msg)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing_response = await client.get("/missing")
        broken_response = await client.get("/broken")

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "detail": "run not found: r",
        "error": {"type": "not_found", "kind": "run", "key": "r"},
    }
    assert broken_response.status_code == 500
