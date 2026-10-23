"""SQLite implementations of the store protocols."""

import builtins
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from git_manager.branches.models import TrackedBranch
from git_manager.core.errors import ConflictError, NotFoundError
from git_manager.events.models import Event, EventDraft
from git_manager.rebasing.models import Run
from git_manager.store.database import Database
from git_manager.store.tables import BranchRow, EventRow, RunRow

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _microseconds(moment: datetime) -> int:
    """``moment`` as whole microseconds since the epoch, exact for any offset."""
    delta = moment - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _flush(session: Session, conflict: str) -> None:
    """Write pending changes now, turning a uniqueness violation into ``ConflictError``."""
    try:
        session.flush()
    except IntegrityError as error:
        raise ConflictError(conflict) from error


class SqlBranchRepository:
    """``BranchRepository`` over the ``branches`` table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def add(self, branch: TrackedBranch) -> None:
        def work(session: Session) -> None:
            session.add(BranchRow(id=branch.id, name=branch.name, data=branch.model_dump_json()))
            _flush(session, f"branch already tracked: {branch.name}")

        await self._database.run(work)

    async def get(self, branch_id: str) -> TrackedBranch | None:
        def work(session: Session) -> TrackedBranch | None:
            row = session.get(BranchRow, branch_id)
            return None if row is None else TrackedBranch.model_validate_json(row.data)

        return await self._database.run(work)

    async def find(self, name: str) -> TrackedBranch | None:
        def work(session: Session) -> TrackedBranch | None:
            row = session.exec(select(BranchRow).where(BranchRow.name == name)).first()
            return None if row is None else TrackedBranch.model_validate_json(row.data)

        return await self._database.run(work)

    async def list(self) -> Sequence[TrackedBranch]:
        def work(session: Session) -> builtins.list[TrackedBranch]:
            rows = session.exec(select(BranchRow).order_by(col(BranchRow.name)))
            return [TrackedBranch.model_validate_json(row.data) for row in rows]

        return await self._database.run(work)

    async def update(self, branch: TrackedBranch) -> None:
        def work(session: Session) -> None:
            row = session.get(BranchRow, branch.id)
            if row is None:
                raise NotFoundError(kind="branch", key=branch.id)
            row.name = branch.name
            row.data = branch.model_dump_json()
            _flush(session, f"branch already tracked: {branch.name}")

        await self._database.run(work)

    async def remove(self, branch_id: str) -> None:
        def work(session: Session) -> None:
            row = session.get(BranchRow, branch_id)
            if row is None:
                raise NotFoundError(kind="branch", key=branch_id)
            session.delete(row)

        await self._database.run(work)


class SqlRunRepository:
    """``RunRepository`` over the ``runs`` table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def add(self, run: Run) -> None:
        def work(session: Session) -> None:
            session.add(
                RunRow(
                    id=run.id,
                    branch_id=run.branch_id,
                    started_at_us=_microseconds(run.started_at),
                    data=run.model_dump_json(),
                )
            )
            _flush(session, f"run already exists: {run.id}")

        await self._database.run(work)

    async def get(self, run_id: str) -> Run | None:
        def work(session: Session) -> Run | None:
            row = session.exec(select(RunRow).where(RunRow.id == run_id)).first()
            return None if row is None else Run.model_validate_json(row.data)

        return await self._database.run(work)

    async def list(self, *, branch_id: str | None = None, limit: int = 50) -> Sequence[Run]:
        def work(session: Session) -> builtins.list[Run]:
            query = select(RunRow)
            if branch_id is not None:
                query = query.where(RunRow.branch_id == branch_id)
            query = query.order_by(col(RunRow.started_at_us).desc(), col(RunRow.seq).desc()).limit(
                limit
            )
            return [Run.model_validate_json(row.data) for row in session.exec(query)]

        return await self._database.run(work)

    async def update(self, run: Run) -> None:
        def work(session: Session) -> None:
            row = session.exec(select(RunRow).where(RunRow.id == run.id)).first()
            if row is None:
                raise NotFoundError(kind="run", key=run.id)
            row.branch_id = run.branch_id
            row.started_at_us = _microseconds(run.started_at)
            row.data = run.model_dump_json()

        await self._database.run(work)


class SqlEventRepository:
    """``EventRepository`` over the ``events`` table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def append(self, draft: EventDraft, *, at: datetime) -> Event:
        def work(session: Session) -> Event:
            # Insert first so SQLite assigns the id the stored JSON then carries.
            row = EventRow(data="")
            session.add(row)
            session.flush()
            event = Event.model_validate(draft.model_dump() | {"id": row.id, "at": at})
            row.data = event.model_dump_json()
            return event

        return await self._database.run(work)

    async def list(self, *, after: int = 0, limit: int = 100) -> Sequence[Event]:
        def work(session: Session) -> builtins.list[Event]:
            query = (
                select(EventRow)
                .where(col(EventRow.id) > after)
                .order_by(col(EventRow.id))
                .limit(limit)
            )
            return [Event.model_validate_json(row.data) for row in session.exec(query)]

        return await self._database.run(work)
