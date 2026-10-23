"""Operations through the REST API, as an httpx client."""

import httpx

from git_manager.health import HealthStatus


class ApiError(Exception):
    """The API answered with an error status."""

    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(f"API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ApiUnreachableError(Exception):
    """The API could not be reached (connection refused, timeout, missing socket)."""


class HttpOperations:
    """Implements ``Operations`` by calling a running daemon's REST API.

    The caller owns the injected client and closes it.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def health(self) -> HealthStatus:
        """Report the daemon's health."""
        response = await self._get("/healthz")
        return HealthStatus.model_validate_json(response.content)

    async def _get(self, path: str) -> httpx.Response:
        try:
            response = await self._client.get(path)
        except httpx.TransportError as error:
            raise ApiUnreachableError(str(error) or type(error).__name__) from error
        if response.is_error:
            raise ApiError(status_code=response.status_code, detail=response.text)
        return response
