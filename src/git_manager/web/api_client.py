"""The REST API's client side: requests, and errors mapped back from responses."""

from collections.abc import AsyncGenerator, Mapping

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from git_manager.core.targets import redact_url
from git_manager.web.errors import ErrorResponse, from_response

# Every route but the OpenAPI pages lives under this prefix.
API_PREFIX = "/api/v1"
# Keeps a proxy's HTML error page from flooding the terminal.
MAX_DETAIL_LENGTH = 200

type QueryParams = Mapping[str, str | int]


class ApiError(Exception):
    """The API answered with an error status that is not an operation's typed error.

    For example ``401`` without a valid token, ``403`` when the token lacks the route's
    scope, ``422`` for a request that fails validation, or a proxy's ``502``.
    """

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


def _raise_for(response: httpx.Response) -> None:
    """Raise the operation's typed error for an error response, or else ``ApiError``."""
    try:
        typed = ErrorResponse.model_validate_json(response.content)
    except ValidationError:
        raise ApiError(status_code=response.status_code, detail=_error_detail(response)) from None
    raise from_response(typed)


class ApiClient:
    """Sends requests to a daemon's REST API and parses typed responses.

    Every domain's HTTP operations share one client. An error response that carries an
    operation error (see ``web.errors``) raises that error, as ``Service`` would; any other
    raises ``ApiError``. The caller owns the injected httpx client and closes it.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get[T](
        self, path: str, response: TypeAdapter[T], *, params: QueryParams | None = None
    ) -> T:
        """GET ``path`` and parse the body as ``response``."""
        return _parse(await self._send("GET", path, params=params), response)

    async def get_text(self, path: str) -> str:
        """GET ``path`` and return the body as text."""
        return (await self._send("GET", path)).text

    async def post[T](
        self,
        path: str,
        response: TypeAdapter[T],
        *,
        body: BaseModel | None = None,
        timeouts: httpx.Timeout | None = None,
    ) -> T:
        """POST ``body`` to ``path`` and parse the response; ``timeouts`` replace the client's."""
        return _parse(await self._send("POST", path, body=body, timeouts=timeouts), response)

    async def patch[T](self, path: str, response: TypeAdapter[T], *, body: BaseModel) -> T:
        """PATCH ``path`` with ``body`` and parse the response."""
        return _parse(await self._send("PATCH", path, body=body), response)

    async def delete(self, path: str) -> None:
        """DELETE ``path``; the response has no body."""
        await self._send("DELETE", path)

    async def stream_lines(
        self, path: str, *, headers: Mapping[str, str] | None = None
    ) -> AsyncGenerator[str]:
        """GET ``path`` and yield its body line by line as it arrives.

        The read timeout is lifted, since a quiet stream is not a dead one; the client's
        connect timeout still applies. Close the generator to leave the stream.
        """
        timeouts = self._client.timeout
        streaming = httpx.Timeout(
            connect=timeouts.connect, read=None, write=timeouts.write, pool=timeouts.pool
        )
        try:
            async with self._client.stream(
                "GET", path, headers=headers, timeout=streaming
            ) as response:
                if response.is_error:
                    await response.aread()
                    _raise_for(response)
                async for line in response.aiter_lines():
                    yield line
        except httpx.TransportError as error:
            raise ApiUnreachableError(str(error) or type(error).__name__) from error

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: QueryParams | None = None,
        body: BaseModel | None = None,
        timeouts: httpx.Timeout | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=None if body is None else body.model_dump(mode="json"),
                timeout=httpx.USE_CLIENT_DEFAULT if timeouts is None else timeouts,
            )
        except httpx.TransportError as error:
            raise ApiUnreachableError(str(error) or type(error).__name__) from error
        if response.is_error:
            _raise_for(response)
        return response


def _parse[T](response: httpx.Response, adapter: TypeAdapter[T]) -> T:
    try:
        return adapter.validate_json(response.content)
    except ValidationError as error:
        url = redact_url(str(response.url))
        msg = f"unexpected response from {url}: {error.error_count()} error(s)"
        raise ApiResponseError(msg) from error
