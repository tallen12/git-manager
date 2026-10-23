import json
import logging
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from git_manager.isolation import LocalProcessRunner
from git_manager.runtime import Command, ProcessCompleted, ProcessUser

PRINT_ENV = "import json, os; print(json.dumps(dict(os.environ)))"
INHERITED = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "GH_TOKEN": "ghp_secret"}


def python(
    code: str,
    *,
    env: Mapping[str, str] | None = None,
    user: ProcessUser = ProcessUser.ORCHESTRATOR,
    stdin: str | None = None,
) -> Command:
    return Command(
        argv=(sys.executable, "-c", code), cwd=Path.cwd(), env=env or {}, user=user, stdin=stdin
    )


async def completed(runner: LocalProcessRunner, command: Command) -> ProcessCompleted:
    result = await runner.run(command)
    assert isinstance(result, ProcessCompleted)
    return result


async def test_commands_get_the_allowlist_plus_their_own_env_and_no_secrets() -> None:
    runner = LocalProcessRunner(inherited=INHERITED)

    result = await completed(runner, python(PRINT_ENV, env={"GM_RUN_ID": "run-1"}))

    env = json.loads(result.stdout)
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["GM_RUN_ID"] == "run-1"
    assert "GH_TOKEN" not in env


async def test_exit_codes_output_and_stdin_are_reported() -> None:
    runner = LocalProcessRunner(inherited=INHERITED)
    code = (
        "import sys; data = sys.stdin.read(); print(data.upper()); "
        "print('e', file=sys.stderr); sys.exit(3)"
    )

    result = await completed(runner, python(code, stdin="hello"))

    assert result.exit_code == 3
    assert not result.succeeded
    assert result.stdout == "HELLO\n"
    assert result.stderr == "e\n"


async def test_a_missing_program_raises_os_error() -> None:
    runner = LocalProcessRunner(inherited=INHERITED)

    with pytest.raises(OSError):
        await runner.run(Command(argv=("gm-no-such-program",), cwd=Path.cwd()))


async def test_isolated_users_log_once_that_isolation_is_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = LocalProcessRunner(inherited=INHERITED)

    with caplog.at_level(logging.WARNING):
        await runner.run(python("pass"))
        assert caplog.records == []
        await runner.run(python("pass", user=ProcessUser.TESTS))
        await runner.run(python("pass", user=ProcessUser.CLAUDE))

    assert len(caplog.records) == 1
    assert "process isolation is off" in caplog.records[0].getMessage()
