"""Isolation contracts."""

from typing import Protocol

from git_manager.isolation.models import SpawnRequest, SpawnResponse


class SupervisorChannel(Protocol):
    """Asks the supervisor to run one command as an isolated user."""

    async def spawn(self, request: SpawnRequest) -> SpawnResponse:
        """Send ``request`` and wait for its answer.

        Cancelling the call closes the exchange, and the supervisor kills the command.
        Raises ``SupervisorError`` when the supervisor cannot be reached or breaks the
        contract.
        """
        ...
