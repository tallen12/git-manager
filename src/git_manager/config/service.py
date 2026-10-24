"""In-process config operations."""

import asyncio

from pydantic import JsonValue

from git_manager.config.models import RepoConfig
from git_manager.config.protocols import ConfigPath, ConfigStore


class ConfigService:
    """``ConfigOperations`` over a ``ConfigStore``, reading it fresh on every call.

    Reading each time means an edit to the file is seen without a restart. File access
    runs in a worker thread so it never blocks the event loop.
    """

    def __init__(self, store: ConfigStore) -> None:
        self._store = store

    async def show(self) -> RepoConfig:
        """Return the effective config; raise ``ConfigError`` if it is invalid."""
        return await asyncio.to_thread(self._store.load)

    async def set(self, path: ConfigPath, value: JsonValue) -> RepoConfig:
        """Edit the file and return the new effective config; raise ``ConfigError``."""
        return await asyncio.to_thread(self._store.set, path, value)
