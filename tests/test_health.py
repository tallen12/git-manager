import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from git_manager.cli.main import build_app
from git_manager.health import HealthReporter
from git_manager.mcp.server import create_server
from git_manager.web.app import create_app
from tests.conftest import TEST_VERSION


def test_rest_health_reports_ok(reporter: HealthReporter) -> None:
    client = TestClient(create_app(reporter=reporter, version=TEST_VERSION))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": TEST_VERSION}


async def test_mcp_health_tool_reports_ok(reporter: HealthReporter) -> None:
    async with Client(create_server(reporter=reporter)) as client:
        result = await client.call_tool("health", {})

    assert result.structured_content == {"status": "ok", "version": TEST_VERSION}


def test_cli_health_prints_json(
    reporter: HealthReporter, capsys: pytest.CaptureFixture[str]
) -> None:
    app = build_app(reporter=reporter, version=TEST_VERSION)

    try:
        app(["health"])
    except SystemExit as exit_:
        assert exit_.code in (0, None)

    assert json.loads(capsys.readouterr().out) == {"status": "ok", "version": TEST_VERSION}


def test_repository_fixture_creates_git_repo(repository: Path) -> None:
    assert (repository / ".git").is_dir()


def test_repository_fixture_ignores_global_and_system_config(repository: Path) -> None:
    listing = subprocess.run(
        ["git", "-C", str(repository), "config", "--list", "--show-scope"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )

    scopes = {line.split("\t", 1)[0] for line in listing.stdout.splitlines()}
    assert scopes == {"local"}
