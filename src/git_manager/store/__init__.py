"""SQLite persistence behind one repository protocol per record type."""

from git_manager.store.protocols import BranchRepository, EventRepository, RunRepository

__all__ = ["BranchRepository", "EventRepository", "RunRepository"]
