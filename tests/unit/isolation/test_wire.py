from pathlib import Path

import pytest

from git_manager.isolation import (
    SpawnCompleted,
    SpawnRequest,
    SpawnTimedOut,
    SupervisorProtocolError,
)
from git_manager.isolation.wire import (
    decode_request,
    decode_response,
    encode_request,
    encode_response,
)
from git_manager.runtime import ProcessUser


def test_requests_round_trip_as_one_line() -> None:
    request = SpawnRequest(
        user=ProcessUser.CLAUDE,
        argv=("claude", "-p", "line one\nline two"),
        cwd=Path.cwd(),
        env={"PATH": "/usr/bin"},
        stdin="input\n",
    )

    line = encode_request(request)

    assert line.endswith(b"\n")
    assert line.count(b"\n") == 1
    assert decode_request(line) == request


def test_responses_round_trip() -> None:
    for response in (
        SpawnCompleted(exit_code=-9, stdout="out", stderr="err", duration_s=1.5),
        SpawnTimedOut(stdout="partial", stderr="", duration_s=60),
    ):
        assert decode_response(encode_response(response)) == response


def test_malformed_messages_are_protocol_errors() -> None:
    with pytest.raises(SupervisorProtocolError, match="spawn request"):
        decode_request(b'{"user": "root"}\n')
    with pytest.raises(SupervisorProtocolError, match="spawn response"):
        decode_response(b"not json\n")


def test_a_closed_connection_is_a_protocol_error() -> None:
    with pytest.raises(SupervisorProtocolError, match="without answering"):
        decode_response(b"")
