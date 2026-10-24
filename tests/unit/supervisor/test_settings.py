from pathlib import Path

import pytest
from pydantic import ValidationError

from git_manager.supervisor.settings import SOCKET_VARIABLE, SupervisorSettings


def test_defaults_match_the_compose_file() -> None:
    settings = SupervisorSettings.from_environ({"PATH": "/bin", "GM_HTTP__PORT": "1"})

    assert settings.socket == Path("/run/gm-supervisor/supervisor.sock")
    assert settings.data_root == Path("/data")
    assert settings.client_certs == Path("/certs/client")
    assert settings.api_socket_dir == Path("/run/git-manager")
    assert settings.secrets_dir == Path("/run/secrets")


def test_supervisor_variables_override_defaults() -> None:
    settings = SupervisorSettings.from_environ(
        {SOCKET_VARIABLE: "/run/s.sock", "GM_SUPERVISOR_OUTPUT_LIMIT_BYTES": "10"}
    )

    assert settings.socket == Path("/run/s.sock")
    assert settings.output_limit_bytes == 10


@pytest.mark.parametrize(
    "environ",
    [{"GM_SUPERVISOR_SOKET": "/x"}, {"GM_SUPERVISOR_OUTPUT_LIMIT_BYTES": "0"}],
)
def test_unknown_or_invalid_variables_are_errors(environ: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        SupervisorSettings.from_environ(environ)
