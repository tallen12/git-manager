"""Operations contract shared by the in-process service and the HTTP client."""

from typing import Protocol

from git_manager.health import HealthStatus


class Operations(Protocol):
    """Every Git Manager operation.

    ``Service`` implements it in-process and ``HttpOperations`` through the REST API, so
    the CLI behaves the same in local and API mode. Add an operation here, to ``Service``,
    to REST and to ``HttpOperations`` together.
    """

    async def health(self) -> HealthStatus:
        """Report whether Git Manager is alive and which version is running."""
        ...
