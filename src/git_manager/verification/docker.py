"""The Docker sidecar as seen by test commands: their environment, and cleanup after."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import assert_never

from git_manager.config.models import DockerConfig, DockerMode
from git_manager.runtime.models import Command, ProcessCompleted, ProcessTimedOut, ProcessUser
from git_manager.runtime.protocols import ProcessRunner
from git_manager.verification.errors import DockerCleanupError, UnsupportedDockerModeError

RUN_LABEL = "gm.run"
"""Label that tests put on what they create, set to the run id passed as ``GM_RUN_ID``."""


def docker_environment(docker: DockerConfig, *, run_id: str) -> dict[str, str]:
    """The variables that let a ``setup`` or ``test`` command reach the Docker daemon.

    Empty when Docker is off. Never includes git, GitHub or Claude credentials: the client
    certificates are files that only ``gm-tests`` can read.
    """
    match docker.mode:
        case DockerMode.NONE:
            return {}
        case DockerMode.DIND:
            return {
                "DOCKER_HOST": docker.host,
                "DOCKER_TLS_VERIFY": "1",
                "DOCKER_CERT_PATH": str(docker.cert_path),
                "GM_RUN_ID": run_id,
            }
        case DockerMode.HOST_SOCKET:
            msg = "verify.docker.mode host_socket is not supported yet; use dind or none"
            raise UnsupportedDockerModeError(msg)
        case _ as unreachable:
            assert_never(unreachable)


class DockerCliCleaner:
    """``DockerCleaner`` that runs the ``docker`` CLI against the sidecar as ``gm-tests``.

    Removes everything labeled ``gm.run=<run-id>``; with ``reset_between_runs`` it also
    prunes stopped containers and networks created before the run, and unused anonymous
    volumes. Images are kept, so the image cache survives between runs.
    """

    def __init__(
        self,
        *,
        runner: ProcessRunner,
        cwd: Path,
        timeout: timedelta = timedelta(minutes=2),
    ) -> None:
        self._runner = runner
        self._cwd = cwd
        self._timeout = timeout

    async def clean_up(self, *, run_id: str, docker: DockerConfig, run_started: datetime) -> None:
        if docker.mode is DockerMode.NONE:
            return
        env = docker_environment(docker, run_id=run_id)
        env.pop("GM_RUN_ID")
        label = f"label={RUN_LABEL}={run_id}"
        failures: list[str] = []
        containers = await self._docker(
            ("ps", "--all", "--quiet", "--filter", label), env, failures
        )
        if containers:
            await self._docker(("rm", "--force", "--volumes", *containers.split()), env, failures)
        await self._docker(("network", "prune", "--force", "--filter", label), env, failures)
        await self._docker(
            ("volume", "prune", "--all", "--force", "--filter", label), env, failures
        )
        if docker.reset_between_runs:
            until = f"until={run_started.isoformat()}"
            await self._docker(("container", "prune", "--force", "--filter", until), env, failures)
            await self._docker(("network", "prune", "--force", "--filter", until), env, failures)
            await self._docker(("volume", "prune", "--force"), env, failures)
        if failures:
            raise DockerCleanupError("; ".join(failures))

    async def _docker(self, args: tuple[str, ...], env: dict[str, str], failures: list[str]) -> str:
        """Run one ``docker`` command; record a failure and go on, so one step cannot block
        the rest of the cleanup."""
        argv = ("docker", *args)
        command = Command(
            argv=argv, cwd=self._cwd, env=env, user=ProcessUser.TESTS, timeout=self._timeout
        )
        name = " ".join(argv)
        try:
            result = await self._runner.run(command)
        except OSError as error:
            failures.append(f"{name}: {error}")
            return ""
        match result:
            case ProcessCompleted(exit_code=0, stdout=stdout):
                return stdout
            case ProcessCompleted(exit_code=code, stderr=stderr):
                failures.append(f"{name} exited {code}: {stderr.strip()}")
            case ProcessTimedOut():
                failures.append(f"{name} timed out")
            case _ as unreachable:
                assert_never(unreachable)
        return ""
