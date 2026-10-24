"""The SQLite database behind the repositories, and where its blocking calls run."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import URL, Engine
from sqlmodel import Session, StaticPool, create_engine

from git_manager.store.migrations import migrate

STATE_DB = "state.db"


def state_db_path(data_dir: Path) -> Path:
    """Where ``state.db`` lives in a data directory."""
    return data_dir / STATE_DB


class Database:
    """An open ``state.db`` whose calls run one at a time on a worker thread.

    One thread keeps the event loop free and serializes writes, so SQLite never has to
    wait on its own lock. Open it with ``open_database`` or ``open_memory_database``.
    """

    def __init__(self, engine: Engine, executor: ThreadPoolExecutor) -> None:
        self._engine = engine
        self._executor = executor

    async def run[T](self, work: Callable[[Session], T]) -> T:
        """Run ``work`` in one transaction on the worker thread and return its result.

        The transaction commits when ``work`` returns and rolls back when it raises.
        """

        def transaction() -> T:
            # expire_on_commit=False: rows stay readable after the commit closes them.
            with Session(self._engine, expire_on_commit=False) as session, session.begin():
                return work(session)

        future: Future[T] = self._executor.submit(transaction)
        return await asyncio.wrap_future(future)


def sqlite_engine(url: URL | str, **options: object) -> Engine:
    """An engine for ``url`` whose transactions cover DDL as well as data."""
    # autocommit=False makes sqlite3 open a transaction before DDL too, so a migration
    # and its version bump commit or roll back together.
    return create_engine(
        url, connect_args={"autocommit": False, "check_same_thread": False}, **options
    )


def _migrate(engine: Engine) -> None:
    with engine.begin() as connection:
        migrate(connection)


@asynccontextmanager
async def _opened(engine: Engine) -> AsyncGenerator[Database]:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="state-db")
    try:
        await asyncio.wrap_future(executor.submit(_migrate, engine))
        yield Database(engine, executor)
    finally:
        await asyncio.wrap_future(executor.submit(engine.dispose))
        executor.shutdown()


@asynccontextmanager
async def open_database(path: Path) -> AsyncGenerator[Database]:
    """Open (creating and migrating as needed) the database file at ``path``.

    Hold the data directory's lock first: the store assumes it is the only writer.
    """
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    async with _opened(sqlite_engine(URL.create("sqlite", database=str(path)))) as database:
        yield database


@asynccontextmanager
async def open_memory_database() -> AsyncGenerator[Database]:
    """Open a new, migrated database that lives only as long as the ``with`` block."""
    # StaticPool: every in-memory connection is its own database, so share one.
    async with _opened(sqlite_engine("sqlite://", poolclass=StaticPool)) as database:
        yield database
