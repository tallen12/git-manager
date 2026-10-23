"""Open the ``Operations`` implementation for a target."""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, assert_never

import httpx

from git_manager.core.http_operations import HttpOperations
from git_manager.core.protocols import Operations
from git_manager.core.settings import HttpTarget, LocalTarget, SocketTarget

# The host part is ignored over a Unix socket, but httpx needs an absolute base URL.
_SOCKET_BASE_URL = "http://git-manager"


class Connector(Protocol):
    """Opens operations for a target and closes whatever it opened on exit."""

    def __call__(
        self, target: LocalTarget | HttpTarget | SocketTarget
    ) -> AbstractAsyncContextManager[Operations]: ...


def build_connector(*, local: Callable[[LocalTarget], Operations]) -> Connector:
    """Build the default connector: in-process for local mode, httpx for API mode."""

    @asynccontextmanager
    async def connect(
        target: LocalTarget | HttpTarget | SocketTarget,
    ) -> AsyncGenerator[Operations]:
        match target:
            case LocalTarget():
                yield local(target)
            case HttpTarget(url=url):
                token = target.bearer_token().get_secret_value()
                headers = {"Authorization": f"Bearer {token}"}
                async with httpx.AsyncClient(base_url=url, headers=headers) as client:
                    yield HttpOperations(client)
            case SocketTarget(socket=socket):
                transport = httpx.AsyncHTTPTransport(uds=str(socket))
                async with httpx.AsyncClient(
                    transport=transport, base_url=_SOCKET_BASE_URL
                ) as client:
                    yield HttpOperations(client)
            case _:
                assert_never(target)

    return connect
