from pathlib import Path

from pydantic import SecretStr

from git_manager.core import (
    HttpOperations,
    HttpTarget,
    LocalTarget,
    Operations,
    SocketTarget,
    build_connector,
)


async def test_local_target_uses_the_local_factory(service: Operations, tmp_path: Path) -> None:
    requested: list[LocalTarget] = []

    def local(target: LocalTarget) -> Operations:
        requested.append(target)
        return service

    config = tmp_path / "config.yaml"
    config.touch()
    target = LocalTarget(config=config)
    async with build_connector(local=local)(target) as operations:
        assert operations is service

    assert requested == [target]


async def test_http_target_opens_api_client(service: Operations) -> None:
    target = HttpTarget(url="https://gm.test", token=SecretStr("token"))

    async with build_connector(local=lambda _target: service)(target) as operations:
        assert isinstance(operations, HttpOperations)


async def test_socket_target_opens_api_client(service: Operations, tmp_path: Path) -> None:
    target = SocketTarget(socket=tmp_path / "api.sock")

    async with build_connector(local=lambda _target: service)(target) as operations:
        assert isinstance(operations, HttpOperations)
