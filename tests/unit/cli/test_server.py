from contextlib import nullcontext
from pathlib import Path

import pytest
from cyclopts import App

from git_manager.cli import server
from git_manager.cli.output import EXIT_FAILED
from git_manager.cli.server import SERVE_NEEDS_CONFIG
from git_manager.core import Operations, build_connector
from tests.conftest import run_cli
from tests.unit.cli.conftest import no_runtime, operations_app


def _unused() -> Operations:
    msg = "not connected in this test"
    raise AssertionError(msg)


def test_register_adds_serve_and_mcp_stdio() -> None:
    app = App(name="git-manager")

    server.register(
        app,
        connect=build_connector(local=lambda _target: nullcontext(_unused())),
        open_runtime=no_runtime,
        version="1.0",
    )

    assert "serve" in app
    assert "stdio" in app["mcp"]


def test_serve_refuses_an_api_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    app = operations_app()

    assert run_cli(app, ["serve", "--socket", str(tmp_path / "api.sock")]) == EXIT_FAILED
    assert capsys.readouterr().err == f"error: {SERVE_NEEDS_CONFIG}\n"
