from sqlalchemy import inspect
from sqlmodel import Session, SQLModel

from git_manager.store.database import Database
from git_manager.store.tables import BranchRow, EventRow, RunRow

TABLES = {BranchRow.__tablename__, RunRow.__tablename__, EventRow.__tablename__}

# Per table: (column, primary key) pairs, unique column sets and indexed column sets.
type Schema = dict[str, tuple[set[tuple[str, bool]], set[tuple[str, ...]], set[tuple[str, ...]]]]


def _declared() -> Schema:
    schema: Schema = {}
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in TABLES:
            continue
        columns = {(column.name, column.primary_key) for column in table.columns}
        unique: set[tuple[str, ...]] = {
            (column.name,) for column in table.columns if column.unique is True
        }
        indexed = {tuple(column.name for column in index.columns) for index in table.indexes}
        schema[table.name] = (columns, unique, indexed)
    return schema


def _migrated(session: Session) -> Schema:
    inspector = inspect(session.connection())
    schema: Schema = {}
    for name in inspector.get_table_names():
        if name == "sqlite_sequence":
            continue
        primary = set(inspector.get_pk_constraint(name)["constrained_columns"])
        columns = {
            (column["name"], column["name"] in primary) for column in inspector.get_columns(name)
        }
        unique = {
            tuple(str(c) for c in constraint["column_names"])
            for constraint in inspector.get_unique_constraints(name)
        }
        indexed = {
            tuple(str(c) for c in index["column_names"])
            for index in inspector.get_indexes(name)
            if not index["unique"]
        }
        schema[name] = (columns, unique, indexed)
    return schema


async def test_tables_match_the_migrated_schema(database: Database) -> None:
    assert await database.run(_migrated) == _declared()
