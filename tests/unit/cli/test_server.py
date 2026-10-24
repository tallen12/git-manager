from contextlib import nullcontext

from cyclopts import App

from git_manager.cli import server
from git_manager.core import Operations, build_connector


def _unused() -> Operations:
    msg = "not connected in this test"
    raise AssertionError(msg)


def test_register_adds_serve_and_mcp_stdio() -> None:
    app = App(name="git-manager")

    server.register(
        app, connect=build_connector(local=lambda _target: nullcontext(_unused())), version="1.0"
    )

    assert "serve" in app
    assert "stdio" in app["mcp"]
