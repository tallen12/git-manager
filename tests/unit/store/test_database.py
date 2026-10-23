from pathlib import Path
from threading import current_thread, main_thread

import pytest
from sqlmodel import Session, select

from git_manager.store import Database, open_memory_database, state_db_path
from git_manager.store.migrations import LATEST_VERSION, schema_version
from git_manager.store.tables import EventRow


def test_state_db_lives_in_the_data_directory() -> None:
    assert state_db_path(Path("data")) == Path("data", "state.db")


async def test_an_opened_database_is_migrated(database: Database) -> None:
    def version(session: Session) -> int:
        return schema_version(session.connection())

    assert await database.run(version) == LATEST_VERSION


async def test_work_runs_off_the_event_loop_thread(database: Database) -> None:
    def thread_name(_session: Session) -> str:
        return current_thread().name

    name = await database.run(thread_name)

    assert name != main_thread().name
    assert name.startswith("state-db")


async def test_work_commits_when_it_returns(database: Database) -> None:
    def insert(session: Session) -> None:
        session.add(EventRow(data="{}"))

    def count(session: Session) -> int:
        return len(session.exec(select(EventRow)).all())

    await database.run(insert)

    assert await database.run(count) == 1


async def test_work_rolls_back_when_it_raises(database: Database) -> None:
    def insert_then_fail(session: Session) -> None:
        session.add(EventRow(data="{}"))
        session.flush()
        raise ValueError("boom")

    def count(session: Session) -> int:
        return len(session.exec(select(EventRow)).all())

    with pytest.raises(ValueError, match="boom"):
        await database.run(insert_then_fail)

    assert await database.run(count) == 0


async def test_memory_databases_are_separate() -> None:
    def insert(session: Session) -> None:
        session.add(EventRow(data="{}"))

    def count(session: Session) -> int:
        return len(session.exec(select(EventRow)).all())

    async with open_memory_database() as first, open_memory_database() as second:
        await first.run(insert)

        assert await second.run(count) == 0
