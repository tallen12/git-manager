"""Framing for supervisor messages: one UTF-8 JSON object per line, one exchange per
connection. Shared by the daemon's client and the supervisor so both parse the same way.
"""

from pydantic import TypeAdapter, ValidationError

from git_manager.isolation.errors import SupervisorProtocolError
from git_manager.isolation.models import SpawnRequest, SpawnResponse

MAX_MESSAGE_BYTES = 64 * 1024**2
"""Longest line either side reads; test output beyond this is a protocol error."""

_RESPONSE: TypeAdapter[SpawnResponse] = TypeAdapter(SpawnResponse)


def encode_request(request: SpawnRequest) -> bytes:
    """Serialize ``request`` as one line."""
    return request.model_dump_json().encode("utf-8") + b"\n"


def decode_request(line: bytes) -> SpawnRequest:
    """Parse one request line. Raises ``SupervisorProtocolError`` if it is not one."""
    try:
        return SpawnRequest.model_validate_json(line)
    except ValidationError as error:
        msg = f"not a spawn request: {error}"
        raise SupervisorProtocolError(msg) from error


def encode_response(response: SpawnResponse) -> bytes:
    """Serialize ``response`` as one line."""
    return _RESPONSE.dump_json(response) + b"\n"


def decode_response(line: bytes) -> SpawnResponse:
    """Parse one response line. Raises ``SupervisorProtocolError`` if it is not one."""
    if not line:
        msg = "the supervisor closed the connection without answering"
        raise SupervisorProtocolError(msg)
    try:
        return _RESPONSE.validate_json(line)
    except ValidationError as error:
        msg = f"not a spawn response: {error}"
        raise SupervisorProtocolError(msg) from error
