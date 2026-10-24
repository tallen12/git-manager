import pytest
from pydantic import ValidationError

from git_manager.web.settings import HttpSettings


def test_defaults_listen_on_localhost_without_tokens_or_socket() -> None:
    assert HttpSettings() == HttpSettings(
        host="127.0.0.1", port=8765, tokens_file=None, socket=None
    )


@pytest.mark.parametrize("port", [0, 65536])
def test_port_must_be_in_range(port: int) -> None:
    with pytest.raises(ValidationError):
        HttpSettings(port=port)
