import stat
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from git_manager.approvals import Authenticator, TokensFileError
from git_manager.core import Operations
from git_manager.web.app import create_app, rest_servers
from git_manager.web.settings import HttpSettings
from tests.conftest import AUTH_HEADERS, TEST_TOKEN, TEST_VERSION


def test_health_endpoint_reports_ok(service: Operations, authenticator: Authenticator) -> None:
    client = TestClient(
        create_app(operations=service, version=TEST_VERSION, authenticator=authenticator)
    )

    response = client.get("/api/v1/healthz", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": TEST_VERSION}


def test_every_route_needs_a_token(service: Operations, authenticator: Authenticator) -> None:
    app = create_app(operations=service, version=TEST_VERSION, authenticator=authenticator)
    client = TestClient(app)
    # The documented API paths: the OpenAPI document and its pages stay open, they do nothing.
    documented: object = app.openapi()["paths"]
    assert isinstance(documented, dict)
    routes = [
        (str(method).upper(), str(path))
        for path, methods in documented.items()
        if isinstance(methods, dict)
        for method in methods
    ]

    assert len(routes) == 14
    for method, path in routes:
        assert client.request(method, path).status_code == 401, (method, path)


def test_every_operation_has_its_route(service: Operations, authenticator: Authenticator) -> None:
    app = create_app(operations=service, version=TEST_VERSION, authenticator=authenticator)
    documented: object = app.openapi()["paths"]
    assert isinstance(documented, dict)

    assert sorted(str(path) for path in documented) == [
        "/api/v1/branches",
        "/api/v1/branches/{branch}",
        "/api/v1/branches/{branch}/pause",
        "/api/v1/branches/{branch}/resume",
        "/api/v1/branches/{branch}/sync",
        "/api/v1/config",
        "/api/v1/events",
        "/api/v1/healthz",
        "/api/v1/repo",
        "/api/v1/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/diff",
        "/api/v1/runs/{run_id}/tests",
    ]


def test_operation_errors_keep_their_status(
    service: Operations, authenticator: Authenticator
) -> None:
    # ``service`` builds no branches, so they raise UnavailableError: 501 with its body.
    client = TestClient(
        create_app(operations=service, version=TEST_VERSION, authenticator=authenticator)
    )

    response = client.get("/api/v1/repo", headers=AUTH_HEADERS)

    assert response.status_code == 501
    assert response.json()["error"]["type"] == "unavailable"


@pytest.fixture
def tokens_file(tmp_path: Path) -> Path:
    path = tmp_path / "tokens.yaml"
    path.write_text(
        f"tokens:\n  - name: operator\n    token: {TEST_TOKEN}\n    scopes: [read]\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def socket_dir() -> Generator[Path]:
    # Unix socket paths are limited to about 100 bytes; pytest's tmp_path can be longer.
    with tempfile.TemporaryDirectory(prefix="gm-") as directory:
        yield Path(directory)


def test_rest_servers_need_a_tokens_file(service: Operations) -> None:
    with (
        pytest.raises(TokensFileError, match="GM_HTTP__TOKENS_FILE"),
        rest_servers(operations=service, http=HttpSettings(), version=TEST_VERSION),
    ):
        pass


def test_rest_servers_serve_tcp_only_without_a_socket(
    service: Operations, tokens_file: Path
) -> None:
    http = HttpSettings(port=9999, tokens_file=tokens_file)

    with rest_servers(operations=service, http=http, version=TEST_VERSION) as servers:
        assert [(server.config.host, server.config.port) for server in servers] == [
            ("127.0.0.1", 9999)
        ]


def test_rest_servers_add_the_socket_and_remove_it_afterwards(
    service: Operations, tokens_file: Path, socket_dir: Path
) -> None:
    socket = socket_dir / "api.sock"
    http = HttpSettings(tokens_file=tokens_file, socket=socket)

    with rest_servers(operations=service, http=http, version=TEST_VERSION) as servers:
        assert len(servers) == 2
        assert servers[1].config.fd is not None
        assert stat.S_IMODE(socket.stat().st_mode) == 0o660

    assert not socket.exists()
