"""Open the ``Operations`` implementation for a CLI target."""

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, assert_never

import httpx

from git_manager.cli.http_operations import HttpOperations
from git_manager.cli.settings import HttpTarget, LocalTarget, SocketTarget
from git_manager.core import Operations

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
            case HttpTarget(url=url, token=token):
                headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
                async with httpx.AsyncClient(base_url=str(url), headers=headers) as client:
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
