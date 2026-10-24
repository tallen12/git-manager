import os
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import pytest

from git_manager.config import CheckoutRepoConfig, ConfigError
from git_manager.core import LocalTarget
from git_manager.core.compose import LocalRuntime, open_local
from git_manager.isolation import LocalProcessRunner
from git_manager.store import DataDirectoryLockedError, FileDataDirectoryLock
from tests.conftest import TEST_VERSION
from tests.integration.cli.conftest import write_config
from tests.integration.rebasing.conftest import Remote, git, make_remote


@pytest.fixture
def remote(tmp_path: Path) -> Remote:
    return make_remote(tmp_path)


@pytest.fixture
def config_file(remote: Remote, tmp_path: Path) -> Path:
    return write_config(tmp_path / "config.yaml", remote=remote, data_dir=tmp_path / "data")


def opened(config: Path) -> AbstractAsyncContextManager[LocalRuntime]:
    environ = dict(os.environ)
    return open_local(
        LocalTarget(config=config),
        environ=environ,
        repo_config=CheckoutRepoConfig(),
        runner=LocalProcessRunner(inherited=environ),
        version=TEST_VERSION,
    )


async def test_opens_the_store_and_clones_the_repo(
    config_file: Path, remote: Remote, tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"

    async with opened(config_file) as runtime:
        assert runtime.config.repo.data_dir == data_dir
        assert (await runtime.service.health.status()).version == TEST_VERSION
        tracked = await runtime.service.branches.track(name="feature/one", base="main")
        assert await runtime.branches.get(tracked.id) == tracked
        assert git(data_dir / "repo", "rev-parse", "origin/main") == remote.fork_point

    # Everything is released and stored: a second open sees the branch.
    async with opened(config_file) as runtime:
        assert [branch.name for branch in await runtime.branches.list()] == ["feature/one"]
        assert (data_dir / "state.db").is_file()


async def test_refuses_a_data_directory_held_by_another_process(
    config_file: Path, tmp_path: Path
) -> None:
    daemon = FileDataDirectoryLock(tmp_path / "data")
    daemon.acquire()
    try:
        with pytest.raises(DataDirectoryLockedError, match="use API mode"):
            async with opened(config_file):
                pass
    finally:
        daemon.release()


async def test_an_invalid_config_takes_no_lock(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(f"repo:\n  data_dir: {tmp_path / 'data'}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"repo\.url"):
        async with opened(config):
            pass

    assert not (tmp_path / "data").exists()
