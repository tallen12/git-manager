"""Store fixtures: each repository fixture runs once per implementation.

Tests written against these fixtures are the protocol contract, so the in-memory fakes
and the SQLite repositories stay interchangeable.
"""

from collections.abc import AsyncGenerator

import pytest

from git_manager.store import (
    BranchRepository,
    Database,
    EventRepository,
    RunRepository,
    SqlBranchRepository,
    SqlEventRepository,
    SqlRunRepository,
    open_memory_database,
)
from tests.conftest import InMemoryBranches, InMemoryEvents, InMemoryRuns

MEMORY = "memory"
SQLITE = "sqlite"


@pytest.fixture
async def database() -> AsyncGenerator[Database]:
    async with open_memory_database() as opened:
        yield opened


@pytest.fixture(params=[MEMORY, SQLITE])
def branches(request: pytest.FixtureRequest, database: Database) -> BranchRepository:
    return InMemoryBranches() if request.param == MEMORY else SqlBranchRepository(database)


@pytest.fixture(params=[MEMORY, SQLITE])
def runs(request: pytest.FixtureRequest, database: Database) -> RunRepository:
    return InMemoryRuns() if request.param == MEMORY else SqlRunRepository(database)


@pytest.fixture(params=[MEMORY, SQLITE])
def events(request: pytest.FixtureRequest, database: Database) -> EventRepository:
    return InMemoryEvents() if request.param == MEMORY else SqlEventRepository(database)
