import asyncio
import json
import shlex
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from git_manager.config import VerifyConfig
from git_manager.isolation import LocalProcessRunner
from git_manager.verification import (
    CommandSource,
    CommandVerifier,
    StepOutcome,
    VerifyCommands,
    VerifyFailed,
    VerifyPassed,
    VerifyStep,
)
from git_manager.verification.verifier import CANNOT_START_EXIT_CODE
from tests.unit.verification.conftest import RecordingDockerCleaner

ORCHESTRATOR_ENV = {
    "PATH": "/usr/bin:/bin",
    "GH_TOKEN": "ghp_secret",
    "ANTHROPIC_API_KEY": "sk-secret",
    "GM_TARGET__TOKEN": "secret",
}
PYTHON = shlex.quote(sys.executable)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def script(worktree: Path, name: str, code: str) -> str:
    """Write ``code`` to ``name`` in the worktree and return the command that runs it."""
    (worktree / name).write_text(code, encoding="utf-8")
    return f"{PYTHON} {name}"


def verifier(cleaner: RecordingDockerCleaner | None = None) -> CommandVerifier:
    return CommandVerifier(
        runner=LocalProcessRunner(inherited=ORCHESTRATOR_ENV, kill_grace=timedelta(seconds=1)),
        cleaner=cleaner or RecordingDockerCleaner(),
        clock=SystemClock(),
    )


def commands(test: str, *, setup: str | None = None, lint: str | None = None) -> VerifyCommands:
    return VerifyCommands(
        setup=setup, test=test, lint=lint, source=CommandSource.CONFIG, source_hash="h"
    )


async def test_a_passing_suite_keeps_its_output_and_junit_report(tmp_path: Path) -> None:
    test = script(
        tmp_path,
        "run_tests.py",
        "import pathlib\n"
        "for number in range(1000): print(f'test {number} ok')\n"
        "pathlib.Path('reports').mkdir()\n"
        "pathlib.Path('reports/junit.xml').write_text('<testsuite tests=\"1000\"/>')\n",
    )
    setup = script(tmp_path, "setup.py", "print('installed')")

    outcome = await verifier().verify(
        worktree=tmp_path, commands=commands(test, setup=setup), config=VerifyConfig(), run_id="r1"
    )

    assert isinstance(outcome, VerifyPassed)
    setup_result, test_result = outcome.results
    assert setup_result.output_tail == "installed\n"
    assert setup_result.junit_xml is None
    assert test_result.output_tail.splitlines()[0] == "test 500 ok"
    assert len(test_result.output_tail.splitlines()) == 500
    assert test_result.junit_xml == '<testsuite tests="1000"/>'


async def test_test_commands_never_see_credentials(tmp_path: Path) -> None:
    test = script(
        tmp_path,
        "env_dump.py",
        "import json, os, pathlib\n"
        "pathlib.Path('env.json').write_text(json.dumps(dict(os.environ)))",
    )
    cleaner = RecordingDockerCleaner()

    await verifier(cleaner).verify(
        worktree=tmp_path, commands=commands(test), config=VerifyConfig(), run_id="r1"
    )

    env = json.loads((tmp_path / "env.json").read_text(encoding="utf-8"))
    assert not {"GH_TOKEN", "ANTHROPIC_API_KEY", "GM_TARGET__TOKEN"} & env.keys()
    assert env["GM_RUN_ID"] == "r1"
    assert env["DOCKER_TLS_VERIFY"] == "1"
    assert [call.run_id for call in cleaner.calls] == ["r1"]


def beats_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


async def test_a_hanging_suite_is_killed_with_its_children_at_the_timeout(
    tmp_path: Path,
) -> None:
    test = script(
        tmp_path,
        "hang.py",
        "import subprocess, sys, time\n"
        'beat = \'import time\\nwhile True:\\n    open("beats", "a").write(".")\\n'
        "    time.sleep(0.02)'\n"
        "subprocess.Popen([sys.executable, '-c', beat])\n"
        "print('started', flush=True)\n"
        "time.sleep(60)\n",
    )
    config = VerifyConfig(timeout=timedelta(seconds=1))
    started = time.monotonic()

    outcome = await verifier().verify(
        worktree=tmp_path, commands=commands(test), config=config, run_id="r1"
    )

    assert time.monotonic() - started < 10
    assert isinstance(outcome, VerifyFailed)
    result = outcome.results[0]
    assert (result.outcome, result.exit_code) == (StepOutcome.TIMED_OUT, None)
    assert result.output_tail == "started\n"
    await asyncio.sleep(0.1)
    before = beats_size(tmp_path / "beats")
    await asyncio.sleep(0.3)
    assert before > 0
    assert beats_size(tmp_path / "beats") == before


async def test_a_flaky_suite_passes_on_retry_and_says_so(tmp_path: Path) -> None:
    test = script(
        tmp_path,
        "flaky.py",
        "import pathlib, sys\n"
        "marker = pathlib.Path('ran-once')\n"
        "if not marker.exists():\n"
        "    marker.touch()\n"
        "    sys.exit('flaked')\n"
        "print('passed')\n",
    )

    outcome = await verifier().verify(
        worktree=tmp_path, commands=commands(test), config=VerifyConfig(retries=1), run_id="r1"
    )

    assert isinstance(outcome, VerifyPassed)
    assert (outcome.results[0].attempts, outcome.results[0].output_tail) == (2, "passed\n")


async def test_a_missing_tool_and_a_failing_lint_fail_their_steps(tmp_path: Path) -> None:
    lint = script(tmp_path, "lint.py", "import sys; sys.exit('E501 line too long')")
    passing = script(tmp_path, "ok.py", "pass")

    missing = await verifier().verify(
        worktree=tmp_path,
        commands=commands(passing, setup="gm-no-such-tool install"),
        config=VerifyConfig(),
        run_id="r1",
    )
    linted = await verifier().verify(
        worktree=tmp_path, commands=commands(passing, lint=lint), config=VerifyConfig(), run_id="r2"
    )

    assert isinstance(missing, VerifyFailed)
    assert missing.failed_step is VerifyStep.SETUP
    assert missing.results[0].exit_code == CANNOT_START_EXIT_CODE
    assert isinstance(linted, VerifyFailed)
    assert linted.failed_step is VerifyStep.LINT
    assert linted.results[-1].output_tail == "E501 line too long\n"
