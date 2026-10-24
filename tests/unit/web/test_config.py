from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from fastapi import APIRouter
from pydantic import JsonValue

from git_manager.config import ConfigError, ConfigOperations, ConfigPath, RepoConfig
from git_manager.web.api_client import ApiError
from git_manager.web.auth import Access
from git_manager.web.config import HttpConfigOperations, config_router
from tests.unit.web.conftest import serving

CONFIG = RepoConfig.model_validate({"repo": {"url": "u"}})


@dataclass(slots=True)
class RecordingConfig:
    """``ConfigOperations`` serving ``CONFIG`` and recording each edit."""

    sets: list[tuple[tuple[str | int, ...], JsonValue]] = field(default_factory=list)

    async def show(self) -> RepoConfig:
        return CONFIG

    async def set(self, path: ConfigPath, value: JsonValue) -> RepoConfig:
        if not path:
            raise ConfigError("c.yaml", ["(root): name the key to set"])
        self.sets.append((tuple(path), value))
        return CONFIG


def config_of(fake: RecordingConfig) -> Callable[[Access], APIRouter]:
    return lambda access: config_router(fake, access=access)


async def test_show_and_set_round_trip() -> None:
    fake = RecordingConfig()
    async with serving(config_of(fake), as_token="operator") as api:
        operations: ConfigOperations = HttpConfigOperations(api)
        shown = await operations.show()
        updated = await operations.set(("branches", 0, "base"), "develop")

    assert shown == updated == CONFIG
    assert fake.sets == [(("branches", 0, "base"), "develop")]


async def test_values_keep_their_json_type() -> None:
    fake = RecordingConfig()
    async with serving(config_of(fake)) as api:
        await HttpConfigOperations(api).set(["defaults", "cadence", "debounce"], {"a": [1, None]})

    assert fake.sets == [(("defaults", "cadence", "debounce"), {"a": [1, None]})]


@pytest.mark.parametrize(
    "path",
    [("defaults", "verify", "test"), ("branches", 0, "claude"), ("budget",), ("unknown",)],
)
async def test_a_sensitive_or_unknown_key_needs_the_approve_scope(
    path: tuple[str | int, ...],
) -> None:
    fake = RecordingConfig()
    async with serving(config_of(fake), as_token="operator") as api:
        with pytest.raises(ApiError) as raised:
            await HttpConfigOperations(api).set(path, "x")

    assert raised.value.status_code == 403
    assert raised.value.detail == "token 'operator' lacks the approve scope"
    assert fake.sets == []


async def test_approve_may_change_a_sensitive_key() -> None:
    fake = RecordingConfig()
    async with serving(config_of(fake), as_token="admin") as api:
        await HttpConfigOperations(api).set(("defaults", "verify", "test"), "just test")

    assert fake.sets == [(("defaults", "verify", "test"), "just test")]


async def test_reading_needs_only_read_and_editing_needs_operate() -> None:
    fake = RecordingConfig()
    async with serving(config_of(fake), as_token="reader") as api:
        operations = HttpConfigOperations(api)
        assert await operations.show() == CONFIG
        with pytest.raises(ApiError) as raised:
            await operations.set(("branches", 0, "base"), "develop")

    assert raised.value.status_code == 403


async def test_an_invalid_edit_raises_the_config_error() -> None:
    async with serving(config_of(RecordingConfig())) as api:
        with pytest.raises(ConfigError) as raised:
            await HttpConfigOperations(api).set((), 1)

    assert raised.value.problems == ("(root): name the key to set",)
