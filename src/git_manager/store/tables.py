"""SQLModel tables of ``state.db``.

Each row keeps its record as the JSON of its C0 model in ``data``, so the stored value
round-trips exactly and new optional fields need no migration. The other columns are
copies of fields the queries filter or sort on. ``migrations`` creates and evolves the
schema; these classes must match its latest version.
"""

from sqlmodel import Field, SQLModel


class BranchRow(SQLModel, table=True):
    """A ``TrackedBranch``."""

    __tablename__ = "branches"

    id: str = Field(primary_key=True)
    name: str = Field(unique=True)
    data: str


class RunRow(SQLModel, table=True):
    """A ``Run``. ``seq`` orders runs that started in the same microsecond."""

    __tablename__ = "runs"

    seq: int | None = Field(default=None, primary_key=True)
    id: str = Field(unique=True)
    branch_id: str = Field(index=True)
    # Microseconds since the epoch: sorts correctly whatever the stored offset.
    started_at_us: int
    data: str


class EventRow(SQLModel, table=True):
    """An ``Event``; ``id`` is the event id."""

    __tablename__ = "events"
    # Ids are never reused, so an SSE client's last-seen id stays meaningful.
    __table_args__ = {"sqlite_autoincrement": True}

    id: int | None = Field(default=None, primary_key=True)
    data: str
