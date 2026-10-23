"""Operations through the REST API, as an httpx client."""

import httpx
from pydantic import BaseModel, ValidationError

from git_manager.core.targets import redact_url
from git_manager.health import HealthStatus

# Keeps a proxy's HTML error page from flooding the terminal.
MAX_DETAIL_LENGTH = 200


class ApiError(Exception):
    """The API answered with an error status."""

    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(f"API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ApiUnreachableError(Exception):
    """The API could not be reached (connection refused, timeout, missing socket)."""


class ApiResponseError(Exception):
    """The API answered with a body that is not the expected schema (not Git Manager?)."""


class _ValidationIssue(BaseModel):
    """One entry of FastAPI's request validation ``detail`` list."""

    loc: list[str | int]
    msg: str


class _ErrorBody(BaseModel):
    """FastAPI's error body; ``detail`` is a string or a list of validation errors."""

    detail: str | list[_ValidationIssue]


def _join_issues(issues: list[_ValidationIssue]) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in issue.loc)}: {issue.msg}" for issue in issues
    )


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = _ErrorBody.model_validate_json(response.content).detail
    except ValidationError:
        text = response.text.strip()
    else:
        text = detail if isinstance(detail, str) else _join_issues(detail)
    if len(text) > MAX_DETAIL_LENGTH:
        return f"{text[:MAX_DETAIL_LENGTH]}..."
    return text


class HttpOperations:
    """Implements ``Operations`` by calling a running daemon's REST API.

    The caller owns the injected client and closes it.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def health(self) -> HealthStatus:
        """Report the daemon's health."""
        response = await self._get("/healthz")
        try:
            return HealthStatus.model_validate_json(response.content)
        except ValidationError as error:
            url = redact_url(str(response.url))
            msg = f"unexpected response from {url}: {error.error_count()} error(s)"
            raise ApiResponseError(msg) from error

    async def _get(self, path: str) -> httpx.Response:
        try:
            response = await self._client.get(path)
        except httpx.TransportError as error:
            raise ApiUnreachableError(str(error) or type(error).__name__) from error
        if response.is_error:
            raise ApiError(status_code=response.status_code, detail=_error_detail(response))
        return response
