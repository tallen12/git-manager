"""Errors every operation may raise, mapped one to one to HTTP statuses by REST.

A leaf module: it imports nothing from Git Manager, so any domain can raise these without
loading ``git_manager.core``, whose package imports the domains back.
"""


class OperationError(Exception):
    """An operation could not be carried out as asked."""


class NotFoundError(OperationError):
    """The named record does not exist (HTTP 404)."""

    def __init__(self, *, kind: str, key: str) -> None:
        super().__init__(f"{kind} not found: {key}")
        self.kind = kind
        self.key = key


class ConflictError(OperationError):
    """The request conflicts with the current state, e.g. tracking a tracked branch (409)."""


class UnavailableError(OperationError):
    """The operation exists but is not available with this target yet (HTTP 501)."""

    def __init__(self, operation: str, *, reason: str) -> None:
        super().__init__(f"{operation} is not available: {reason}")
        self.operation = operation
        self.reason = reason
