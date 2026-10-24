from collections.abc import Generator

import pytest
from sqlalchemy import Connection, Engine, inspect
from sqlalchemy.exc import OperationalError
from sqlmodel import StaticPool

from git_manager.store.database import sqlite_engine
from git_manager.store.errors import SchemaVersionError
from git_manager.store.migrations import LATEST_VERSION, MIGRATIONS, migrate, schema_version


@pytest.fixture
def engine() -> Generator[Engine]:
    engine = sqlite_engine("sqlite://", poolclass=StaticPool)
    yield engine
    engine.dispose()


def _tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names()) - {"sqlite_sequence"}


def test_a_new_database_is_migrated_to_the_latest_version(engine: Engine) -> None:
    with engine.begin() as connection:
        assert schema_version(connection) == 0
        assert migrate(connection) == LATEST_VERSION == len(MIGRATIONS)

    with engine.connect() as connection:
        assert schema_version(connection) == LATEST_VERSION
        assert _tables(connection) == {"branches", "runs", "events"}


def test_migrating_again_changes_nothing(engine: Engine) -> None:
    with engine.begin() as connection:
        migrate(connection)
    with engine.begin() as connection:
        assert migrate(connection) == LATEST_VERSION


def test_only_unseen_steps_run(engine: Engine) -> None:
    first = ("CREATE TABLE a (x INTEGER)",)
    second = ("ALTER TABLE a ADD COLUMN y INTEGER",)
    with engine.begin() as connection:
        migrate(connection, migrations=(first,))
    with engine.begin() as connection:
        assert migrate(connection, migrations=(first, second)) == 2
        columns = [column["name"] for column in inspect(connection).get_columns("a")]

    assert columns == ["x", "y"]


def test_a_failed_step_leaves_the_database_unchanged(engine: Engine) -> None:
    broken = ("CREATE TABLE a (x INTEGER)", "CREATE TABLE a (x INTEGER)")

    with pytest.raises(OperationalError), engine.begin() as connection:
        migrate(connection, migrations=(broken,))

    with engine.connect() as connection:
        assert schema_version(connection) == 0
        assert _tables(connection) == set()


def test_a_newer_database_is_refused(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(f"PRAGMA user_version = {LATEST_VERSION + 1}")

    with pytest.raises(SchemaVersionError) as caught, engine.begin() as connection:
        migrate(connection)

    assert caught.value.found == LATEST_VERSION + 1
    assert caught.value.supported == LATEST_VERSION
