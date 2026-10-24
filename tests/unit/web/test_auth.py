from typing import Annotated

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import SecretStr

from git_manager.approvals import (
    ApiToken,
    Principal,
    Scope,
    TokenAuthenticator,
    TokensFile,
    TrustedAuthenticator,
)
from git_manager.approvals.protocols import Authenticator
from git_manager.web.auth import Access, demand

AGENT = "mcp-agent-token-0123456789abcdef012"


def agent_only() -> TokenAuthenticator:
    entry = ApiToken(
        name="mcp-agent", token=SecretStr(AGENT), scopes=frozenset({Scope.READ, Scope.OPERATE})
    )
    return TokenAuthenticator(TokensFile(tokens=(entry,)))


def app_needing(scope: Scope, authenticator: Authenticator) -> FastAPI:
    app = FastAPI()
    access = Access(authenticator)

    @app.get("/thing")
    async def thing(principal: Annotated[Principal, access.requires(scope)]) -> str:
        return principal.name

    return app


async def get(app: FastAPI, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/thing", headers=headers)


async def test_a_token_with_the_scope_is_admitted_as_its_principal() -> None:
    response = await get(
        app_needing(Scope.OPERATE, agent_only()), {"Authorization": f"Bearer {AGENT}"}
    )

    assert response.status_code == httpx.codes.OK
    assert response.json() == "mcp-agent"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {AGENT}"}],
    ids=["none", "unknown", "not-bearer"],
)
async def test_a_request_without_a_valid_token_gets_401(headers: dict[str, str]) -> None:
    response = await get(app_needing(Scope.READ, agent_only()), headers)

    assert response.status_code == httpx.codes.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "missing or invalid API token"}


async def test_a_token_without_the_scope_gets_403_naming_it() -> None:
    response = await get(
        app_needing(Scope.APPROVE, agent_only()), {"Authorization": f"Bearer {AGENT}"}
    )

    assert response.status_code == httpx.codes.FORBIDDEN
    assert response.json() == {"detail": "token 'mcp-agent' lacks the approve scope"}


async def test_the_socket_needs_no_token_for_any_scope() -> None:
    response = await get(app_needing(Scope.APPROVE, TrustedAuthenticator()), {})

    assert response.status_code == httpx.codes.OK
    assert response.json() == "socket"


def test_demand_passes_a_holder_and_refuses_anyone_else_with_403() -> None:
    agent = Principal(name="mcp-agent", scopes=frozenset({Scope.READ, Scope.OPERATE}))

    demand(agent, Scope.OPERATE)
    with pytest.raises(HTTPException) as raised:
        demand(agent, Scope.APPROVE)

    assert raised.value.status_code == httpx.codes.FORBIDDEN
    assert raised.value.detail == "token 'mcp-agent' lacks the approve scope"
