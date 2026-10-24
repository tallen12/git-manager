import os
import socket
import struct
import sys
from pathlib import Path

import pytest

from git_manager.supervisor.linux import (
    ProcCapabilities,
    SoPeerCredentials,
    parse_capabilities,
    parse_ucred,
)
from git_manager.supervisor.models import CapabilitySets

STATUS = """Name:\tgit-manager-sup
Uid:\t0\t0\t0\t0
CapInh:\t0000000000000000
CapPrm:\t00000000000000e1
CapEff:\t00000000000000e1
CapBnd:\t00000000000000e1
CapAmb:\t0000000000000000
"""


def test_capabilities_come_from_the_status_file(tmp_path: Path) -> None:
    status = tmp_path / "status"
    status.write_text(STATUS, encoding="utf-8")

    assert ProcCapabilities(status_file=status).current() == CapabilitySets(
        effective=0xE1, bounding=0xE1
    )


def test_a_status_without_capabilities_is_an_error() -> None:
    with pytest.raises(ValueError, match="CapEff"):
        parse_capabilities("Name:\tx\nCapEff:\tzz\n")


def test_ucred_holds_pid_uid_and_gid() -> None:
    assert parse_ucred(struct.pack("3i", 42, 10001, 10002)) == 10001


@pytest.mark.skipif(sys.platform != "linux", reason="SO_PEERCRED is Linux-only")
def test_peer_credentials_name_the_connected_process() -> None:
    left, right = socket.socketpair(socket.AF_UNIX)
    with left, right:
        assert SoPeerCredentials().peer_uid(left.fileno()) == os.geteuid()
        left.sendall(b"still open")
        assert right.recv(10) == b"still open"
