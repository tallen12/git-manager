import json

import httpx
import pytest
from pydantic import BaseModel, TypeAdapter

from git_manager.errors import ConflictError, NotFoundError
from git_manager.health import HealthStatus
from git_manager.web.api_client import (
    MAX_DETAIL_LENGTH,
    ApiClient,
    ApiError,
    ApiResponseError,
    ApiUnreachableError,
)

HEALTH = TypeAdapter(HealthStatus)


async def test_get_parses_the_response_body() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(200, json={"status": "ok", "version": "1.2.3"})

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = await ApiClient(client).get("/healthz", HEALTH)

    assert status == HealthStatus(status="ok", version="1.2.3")


async def test_error_status_raises_api_error() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(403, text="missing scope"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ApiError) as raised:
            await ApiClient(client).get("/healthz", HEALTH)

    assert raised.value.status_code == 403
    assert raised.value.detail == "missing scope"


async def test_transport_failure_raises_unreachable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(refuse), base_url="http://test"
    ) as client:
        with pytest.raises(ApiUnreachableError, match="connection refused"):
            await ApiClient(client).get("/healthz", HEALTH)


async def test_fastapi_error_detail_is_unwrapped() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(401, json={"detail": "Not authenticated"})
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ApiError) as raised:
            await ApiClient(client).get("/healthz", HEALTH)

    assert raised.value.detail == "Not authenticated"


async def test_long_error_body_is_truncated() -> None:
    page = "<html>" + "x" * 5000 + "</html>"
    transport = httpx.MockTransport(lambda _request: httpx.Response(502, text=page))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ApiError) as raised:
            await ApiClient(client).get("/healthz", HEALTH)

    assert raised.value.detail == page[:MAX_DETAIL_LENGTH] + "..."


async def test_unexpected_body_raises_response_error() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text="<html></html>"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ApiResponseError, match="unexpected response from http://test/healthz"):
            await ApiClient(client).get("/healthz", HEALTH)


async def test_validation_error_detail_lists_each_issue() -> None:
    body = {
        "detail": [
            {"type": "missing", "loc": ["body", "branch"], "msg": "Field required"},
            {"type": "int_parsing", "loc": ["query", "limit"], "msg": "Input should be int"},
        ]
    }
    transport = httpx.MockTransport(lambda _request: httpx.Response(422, json=body))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ApiError) as raised:
            await ApiClient(client).get("/healthz", HEALTH)

    assert raised.value.detail == "body.branch: Field required; query.limit: Input should be int"


async def test_unexpected_body_error_hides_url_password() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text="<html></html>"))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://alice:hunter2@test"
    ) as client:
        with pytest.raises(ApiResponseError) as raised:
            await ApiClient(client).get("/healthz", HEALTH)

    assert "hunter2" not in str(raised.value)


class Change(BaseModel):
    name: str


def recorder(requests: list[httpx.Request], response: httpx.Response) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    return httpx.MockTransport(respond)


async def test_post_sends_the_body_as_json_with_the_given_timeouts() -> None:
    requests: list[httpx.Request] = []
    transport = recorder(requests, httpx.Response(201, json={"status": "ok", "version": "1"}))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = await ApiClient(client).post(
            "/things", HEALTH, body=Change(name="a"), timeouts=httpx.Timeout(1.0, read=None)
        )

    assert status.version == "1"
    assert requests[0].method == "POST"
    assert json.loads(requests[0].content) == {"name": "a"}
    assert requests[0].extensions["timeout"]["read"] is None


async def test_patch_sends_the_body_and_delete_expects_no_body() -> None:
    requests: list[httpx.Request] = []
    transport = recorder(requests, httpx.Response(200, json={"status": "ok", "version": "1"}))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        api = ApiClient(client)
        await api.patch("/things", HEALTH, body=Change(name="b"))
        await api.delete("/things/b")

    assert [(request.method, request.url.path) for request in requests] == [
        ("PATCH", "/things"),
        ("DELETE", "/things/b"),
    ]
    assert json.loads(requests[0].content) == {"name": "b"}


async def test_get_sends_params_and_get_text_returns_the_body() -> None:
    requests: list[httpx.Request] = []
    transport = recorder(requests, httpx.Response(200, text="diff --git a b\n"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        text = await ApiClient(client).get_text("/diff")
        with pytest.raises(ApiResponseError):
            await ApiClient(client).get("/runs", HEALTH, params={"limit": 5, "branch": "f/x"})

    assert text == "diff --git a b\n"
    assert dict(requests[1].url.params) == {"limit": "5", "branch": "f/x"}


async def test_operation_error_body_raises_the_typed_error() -> None:
    body = {"detail": "run not found: r", "error": {"type": "not_found", "kind": "run", "key": "r"}}
    transport = httpx.MockTransport(lambda _request: httpx.Response(404, json=body))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(NotFoundError) as raised:
            await ApiClient(client).delete("/runs/r")

    assert (raised.value.kind, raised.value.key) == ("run", "r")


async def test_conflict_body_keeps_the_server_message() -> None:
    body = {"detail": "cannot sync f: it is paused", "error": {"type": "conflict"}}
    transport = httpx.MockTransport(lambda _request: httpx.Response(409, json=body))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(ConflictError, match=r"^cannot sync f: it is paused$"):
            await ApiClient(client).post("/branches/f/sync", HEALTH)
