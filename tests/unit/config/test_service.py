from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from git_manager.config import ConfigError, ConfigOperations, ConfigService, RepoConfig
from git_manager.config.protocols import ConfigPath


@dataclass
class FakeStore:
    """``ConfigStore`` serving a fixed config, or failing like an invalid file."""

    config: RepoConfig | None
    loads: int = 0
    sets: list[tuple[Sequence[str | int], object]] = field(default_factory=list)

    def load(self) -> RepoConfig:
        self.loads += 1
        if self.config is None:
            raise ConfigError("c.yaml", ["repo.url: missing"])
        return self.config

    def set(self, path: ConfigPath, value: object) -> RepoConfig:
        self.sets.append((path, value))
        return self.load()


async def test_show_returns_the_store_config_read_on_every_call() -> None:
    config = RepoConfig.model_validate({"repo": {"url": "u"}})
    store = FakeStore(config)
    operations: ConfigOperations = ConfigService(store)

    assert await operations.show() == config
    assert await operations.show() == config
    assert store.loads == 2


async def test_show_raises_the_store_config_error() -> None:
    with pytest.raises(ConfigError, match=r"repo\.url: missing"):
        await ConfigService(FakeStore(None)).show()


async def test_set_edits_the_store_and_returns_the_new_config() -> None:
    config = RepoConfig.model_validate({"repo": {"url": "u"}})
    store = FakeStore(config)

    updated = await ConfigService(store).set(("defaults", "cadence", "mode"), "manual")

    assert updated == config
    assert store.sets == [(("defaults", "cadence", "mode"), "manual")]
