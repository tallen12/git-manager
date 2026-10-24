"""Operation errors over REST: the status and body each maps to, and back again.

``Service`` raises typed errors; the routes answer them with one status each and a body
that names the error's type, and ``ApiClient`` raises the same typed error from that body.
CLI output therefore does not depend on the mode.
"""

from typing import Annotated, Literal, assert_never

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Discriminator

from git_manager.config.errors import ConfigError
from git_manager.errors import ConflictError, NotFoundError, OperationError, UnavailableError


class NotFoundBody(BaseModel):
    """``NotFoundError`` (``404``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["not_found"] = "not_found"
    kind: str
    key: str


class ConflictBody(BaseModel):
    """``ConflictError`` (``409``); its message is the response's ``detail``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["conflict"] = "conflict"


class UnavailableBody(BaseModel):
    """``UnavailableError`` (``501``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["unavailable"] = "unavailable"
    operation: str
    reason: str


class InvalidConfigBody(BaseModel):
    """``ConfigError`` (``422``): the config, or an edit to it, is invalid."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["invalid_config"] = "invalid_config"
    source: str
    problems: tuple[str, ...]


class FailedBody(BaseModel):
    """Any other ``OperationError`` (``400``); its message is the response's ``detail``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["failed"] = "failed"


type ErrorBody = Annotated[
    NotFoundBody | ConflictBody | UnavailableBody | InvalidConfigBody | FailedBody,
    Discriminator("type"),
]


class ErrorResponse(BaseModel):
    """What a route answers when its operation raises an ``OperationError``.

    ``detail`` is the error's message, under the key FastAPI uses for its own errors, so a
    client that knows only that key still shows something useful.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: str
    error: ErrorBody


# For the OpenAPI document: every route may answer with these.
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse}
    for code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_501_NOT_IMPLEMENTED,
    )
}


def to_response(error: OperationError) -> tuple[int, ErrorResponse]:
    """The status and body that stand for ``error``; subclasses map like their parent."""
    body: ErrorBody
    match error:
        case NotFoundError(kind=kind, key=key):
            code, body = status.HTTP_404_NOT_FOUND, NotFoundBody(kind=kind, key=key)
        case ConflictError():
            code, body = status.HTTP_409_CONFLICT, ConflictBody()
        case UnavailableError(operation=operation, reason=reason):
            code = status.HTTP_501_NOT_IMPLEMENTED
            body = UnavailableBody(operation=operation, reason=reason)
        case ConfigError(source=source, problems=problems):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
            body = InvalidConfigBody(source=source, problems=problems)
        case _:
            code, body = status.HTTP_400_BAD_REQUEST, FailedBody()
    return code, ErrorResponse(detail=str(error), error=body)


def from_response(response: ErrorResponse) -> OperationError:
    """The typed error ``response`` stands for, with the message the server raised."""
    match response.error:
        case NotFoundBody(kind=kind, key=key):
            return NotFoundError(kind=kind, key=key)
        case ConflictBody():
            return ConflictError(response.detail)
        case UnavailableBody(operation=operation, reason=reason):
            return UnavailableError(operation, reason=reason)
        case InvalidConfigBody(source=source, problems=problems):
            return ConfigError(source, problems)
        case FailedBody():
            return OperationError(response.detail)
        case _:
            assert_never(response.error)


async def _handle(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, OperationError):
        # Only registered for OperationError; anything else is FastAPI's to answer.
        raise error
    code, body = to_response(error)
    return JSONResponse(status_code=code, content=body.model_dump(mode="json"))


def add_error_handlers(app: FastAPI) -> None:
    """Answer every ``OperationError`` a route raises with its status and typed body."""
    app.add_exception_handler(OperationError, _handle)
