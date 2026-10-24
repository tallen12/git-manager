"""Running a branch's verify commands as ``gm-tests``."""

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import assert_never

from git_manager.config.models import VerifyConfig
from git_manager.runtime.models import (
    Command,
    ProcessCompleted,
    ProcessResult,
    ProcessTimedOut,
    ProcessUser,
)
from git_manager.runtime.protocols import Clock, ProcessRunner
from git_manager.verification.commands import split_command
from git_manager.verification.docker import docker_environment
from git_manager.verification.errors import DockerCleanupError
from git_manager.verification.junit import find_junit_xml
from git_manager.verification.models import (
    StepOutcome,
    TestResult,
    VerifyCommands,
    VerifyFailed,
    VerifyOutcome,
    VerifyPassed,
    VerifyStep,
)
from git_manager.verification.output import combined_output, tail_lines
from git_manager.verification.protocols import DockerCleaner

_LOGGER = logging.getLogger(__name__)

CANNOT_START_EXIT_CODE = 127
"""Reported when a step's program cannot be started, as a POSIX shell does."""

# Steps that may reach the Docker sidecar; lint never needs it.
_DOCKER_STEPS = frozenset({VerifyStep.SETUP, VerifyStep.TEST})


@dataclass(frozen=True, slots=True)
class _Attempt:
    result: ProcessResult
    started: datetime


class CommandVerifier:
    """``Verifier`` that runs ``setup``, ``test`` and ``lint`` through a ``ProcessRunner``.

    Every step runs as ``gm-tests`` in the worktree with no credentials: its environment
    holds only the Docker variables (``setup`` and ``test`` in ``dind`` mode), on top of
    the runner's non-secret allowlist. Each attempt gets ``config.timeout``; only ``test``
    is retried, up to ``config.retries`` times. Whatever the outcome, the run's Docker
    leftovers are cleaned up afterwards.
    """

    def __init__(
        self,
        *,
        runner: ProcessRunner,
        cleaner: DockerCleaner,
        clock: Clock,
        logger: logging.Logger = _LOGGER,
    ) -> None:
        self._runner = runner
        self._cleaner = cleaner
        self._clock = clock
        self._logger = logger

    async def verify(
        self, *, worktree: Path, commands: VerifyCommands, config: VerifyConfig, run_id: str
    ) -> VerifyOutcome:
        started = self._clock.now()
        docker_env = docker_environment(config.docker, run_id=run_id)
        steps = [
            (step, command)
            for step, command in (
                (VerifyStep.SETUP, commands.setup),
                (VerifyStep.TEST, commands.test),
                (VerifyStep.LINT, commands.lint),
            )
            if command is not None
        ]
        results: list[TestResult] = []
        try:
            for step, command in steps:
                env = docker_env if step in _DOCKER_STEPS else {}
                result = await self._run_step(
                    step, command, worktree=worktree, env=env, config=config
                )
                results.append(result)
                if result.outcome is not StepOutcome.PASSED:
                    return VerifyFailed(results=tuple(results), failed_step=step)
            return VerifyPassed(results=tuple(results))
        finally:
            await self._clean_up(run_id=run_id, config=config, started=started)

    async def _run_step(
        self,
        step: VerifyStep,
        command: str,
        *,
        worktree: Path,
        env: Mapping[str, str],
        config: VerifyConfig,
    ) -> TestResult:
        process = Command(
            argv=split_command(command),
            cwd=worktree,
            env=env,
            user=ProcessUser.TESTS,
            timeout=config.timeout,
        )
        max_attempts = 1 + (config.retries if step is VerifyStep.TEST else 0)
        duration = timedelta(0)
        attempts = 0
        while True:
            attempts += 1
            attempt = await self._attempt(process)
            duration += attempt.result.duration
            passed = isinstance(attempt.result, ProcessCompleted) and attempt.result.succeeded
            if passed or attempts == max_attempts:
                break
            self._logger.info("%s failed on attempt %d; retrying", step, attempts)
        junit = await asyncio.to_thread(find_junit_xml, worktree, since=attempt.started)
        return _test_result(
            step, command, attempt.result, attempts=attempts, duration=duration, junit=junit
        )

    async def _attempt(self, command: Command) -> _Attempt:
        started = self._clock.now()
        try:
            result = await self._runner.run(command)
        except OSError as error:
            # A missing program is a failed step (the run reports missing_tool), not a crash.
            result = ProcessCompleted(
                exit_code=CANNOT_START_EXIT_CODE,
                stdout="",
                stderr=f"cannot start {command.argv[0]!r}: {error}\n",
                duration=timedelta(0),
            )
        return _Attempt(result=result, started=started)

    async def _clean_up(self, *, run_id: str, config: VerifyConfig, started: datetime) -> None:
        try:
            await self._cleaner.clean_up(run_id=run_id, docker=config.docker, run_started=started)
        except DockerCleanupError:
            # Leftovers do not change what the tests reported; the next run's reset or an
            # operator removes them.
            self._logger.exception("cleaning up Docker after run %s failed", run_id)


def _test_result(
    step: VerifyStep,
    command: str,
    result: ProcessResult,
    *,
    attempts: int,
    duration: timedelta,
    junit: str | None,
) -> TestResult:
    match result:
        case ProcessCompleted(exit_code=code, stdout=stdout, stderr=stderr):
            outcome = StepOutcome.PASSED if code == 0 else StepOutcome.FAILED
            exit_code: int | None = code
        case ProcessTimedOut(stdout=stdout, stderr=stderr):
            outcome = StepOutcome.TIMED_OUT
            exit_code = None
        case _ as unreachable:
            assert_never(unreachable)
    return TestResult(
        step=step,
        command=command,
        outcome=outcome,
        exit_code=exit_code,
        attempts=attempts,
        duration_s=duration.total_seconds(),
        output_tail=tail_lines(combined_output(stdout, stderr)),
        junit_xml=junit,
    )
