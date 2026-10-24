"""``state.db`` as a real file."""

import asyncio
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from git_manager.store import (
    FileDataDirectoryLock,
    SchemaVersionError,
    SqlBranchRepository,
    held,
    open_database,
    state_db_path,
)
from git_manager.store.migrations import LATEST_VERSION
from tests.conftest import make_branch


async def test_opening_creates_and_migrates_the_file(tmp_path: Path) -> None:
    path = state_db_path(tmp_path / "data")

    async with open_database(path):
        pass

    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (LATEST_VERSION,)


async def test_state_survives_reopening(tmp_path: Path) -> None:
    path = state_db_path(tmp_path)
    branch = make_branch()

    async with open_database(path) as database:
        await SqlBranchRepository(database).add(branch)
    async with open_database(path) as database:
        assert await SqlBranchRepository(database).get(branch.id) == branch


async def test_a_database_from_a_newer_version_is_refused(tmp_path: Path) -> None:
    path = state_db_path(tmp_path)
    with closing(sqlite3.connect(path, autocommit=True)) as connection:
        connection.execute(f"PRAGMA user_version = {LATEST_VERSION + 1}")

    with pytest.raises(SchemaVersionError):
        async with open_database(path):
            pass


async def test_a_local_command_opens_the_store_under_the_lock(tmp_path: Path) -> None:
    branch = make_branch()

    with held(FileDataDirectoryLock(tmp_path)):
        async with open_database(state_db_path(tmp_path)) as database:
            await SqlBranchRepository(database).add(branch)

    names = await asyncio.to_thread(os.listdir, tmp_path)
    assert sorted(names) == ["git-manager.lock", "state.db"]
