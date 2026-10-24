"""Config over REST: the routes and their client mirror."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from git_manager.approvals import Principal, Scope
from git_manager.config.models import RepoConfig
from git_manager.config.protocols import ConfigOperations, ConfigPath
from git_manager.config.sensitivity import is_sensitive
from git_manager.web.api_client import API_PREFIX, ApiClient
from git_manager.web.auth import Access, demand
from git_manager.web.errors import ERROR_RESPONSES

CONFIG_PATH = f"{API_PREFIX}/config"

_CONFIG = TypeAdapter(RepoConfig)


class ConfigChange(BaseModel):
    """``PATCH /config``: set ``value`` at ``path`` (YAML keys and list indexes)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # No minimum length: the config file answers an empty path with its own ConfigError,
    # as it does in local mode.
    path: tuple[str | int, ...]
    value: JsonValue


def config_router(operations: ConfigOperations, *, access: Access) -> APIRouter:
    """Routes for ``ConfigOperations``."""
    router = APIRouter(tags=["config"], responses=ERROR_RESPONSES)

    @router.get(CONFIG_PATH, dependencies=[access.requires(Scope.READ)])
    async def show_config() -> RepoConfig:
        return await operations.show()

    @router.patch(CONFIG_PATH)
    async def set_config(
        change: ConfigChange,
        principal: Annotated[Principal, access.requires(Scope.OPERATE)],
    ) -> RepoConfig:
        """Set one config value; a sensitive key needs the ``approve`` scope as well."""
        if is_sensitive(RepoConfig, change.path):
            demand(principal, Scope.APPROVE)
        return await operations.set(change.path, change.value)

    return router


@dataclass(frozen=True, slots=True)
class HttpConfigOperations:
    """``ConfigOperations`` through the REST API."""

    api: ApiClient

    async def show(self) -> RepoConfig:
        """Return the daemon's effective config."""
        return await self.api.get(CONFIG_PATH, _CONFIG)

    async def set(self, path: ConfigPath, value: JsonValue) -> RepoConfig:
        """Set the value at ``path`` in the daemon's config file."""
        change = ConfigChange(path=tuple(path), value=value)
        return await self.api.patch(CONFIG_PATH, _CONFIG, body=change)
