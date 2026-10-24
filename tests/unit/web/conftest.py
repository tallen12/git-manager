"""Serve one router in process, and call it as a token with chosen scopes."""

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI
from pydantic import SecretStr

from git_manager.approvals import ApiToken, Scope, TokenAuthenticator, TokensFile
from git_manager.web.api_client import ApiClient
from git_manager.web.auth import Access
from git_manager.web.errors import add_error_handlers

# One token per scope set a route test needs, named after what it may do.
TOKENS = {
    "reader": frozenset({Scope.READ}),
    "operator": frozenset({Scope.READ, Scope.OPERATE}),
    "admin": frozenset(Scope),
}


def _token(name: str) -> str:
    return f"{name}-token-".ljust(32, "0")


def _authenticator() -> TokenAuthenticator:
    entries = tuple(
        ApiToken(name=name, token=SecretStr(_token(name)), scopes=scopes)
        for name, scopes in TOKENS.items()
    )
    return TokenAuthenticator(TokensFile(tokens=entries))


@asynccontextmanager
async def serving(
    router: Callable[[Access], APIRouter], *, as_token: str = "admin"
) -> AsyncGenerator[ApiClient]:
    """An ``ApiClient`` calling ``router``, as built for ``Access``, with ``as_token``."""
    app = FastAPI()
    add_error_handlers(app)
    app.include_router(router(Access(_authenticator())))
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {_token(as_token)}"}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as client:
        yield ApiClient(client)
