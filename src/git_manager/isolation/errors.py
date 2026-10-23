"""Isolation errors: the supervisor channel failing, as opposed to a command failing."""


class SupervisorError(Exception):
    """The supervisor could not be asked, or answered outside the contract."""


class SupervisorUnavailableError(SupervisorError):
    """The supervisor's socket could not be reached."""


class SupervisorProtocolError(SupervisorError):
    """A message broke the contract in ``isolation.models``, or no answer came."""
