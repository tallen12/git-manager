from pathlib import Path

from pydantic import HttpUrl, SecretStr

from git_manager.cli.connect import build_connector
from git_manager.cli.http_operations import HttpOperations
from git_manager.cli.settings import HttpTarget, LocalTarget, SocketTarget
from git_manager.core import Operations


async def test_local_target_uses_the_local_factory(service: Operations, tmp_path: Path) -> None:
    requested: list[LocalTarget] = []

    def local(target: LocalTarget) -> Operations:
        requested.append(target)
        return service

    target = LocalTarget(config=tmp_path / "config.yaml")
    async with build_connector(local=local)(target) as operations:
        assert operations is service

    assert requested == [target]


async def test_http_target_opens_api_client(service: Operations) -> None:
    target = HttpTarget(url=HttpUrl("http://gm.test"), token=SecretStr("token"))

    async with build_connector(local=lambda _target: service)(target) as operations:
        assert isinstance(operations, HttpOperations)


async def test_socket_target_opens_api_client(service: Operations, tmp_path: Path) -> None:
    target = SocketTarget(socket=tmp_path / "api.sock")

    async with build_connector(local=lambda _target: service)(target) as operations:
        assert isinstance(operations, HttpOperations)
