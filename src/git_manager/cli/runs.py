"""Run commands: ``runs``, ``show``, ``diff`` and ``logs``."""

from collections.abc import Sequence
from typing import Annotated

from cyclopts import App, Parameter

from git_manager.cli.output import reported, short, table
from git_manager.core import Connector, Settings
from git_manager.rebasing.models import Run
from git_manager.verification.models import TestResult


def runs_text(runs: Sequence[Run]) -> str:
    """A table of runs, newest first."""
    if not runs:
        return "no runs"
    rows = [
        (
            run.id,
            run.heads[0].branch,
            str(run.trigger),
            str(run.outcome),
            run.reason or "",
            short(run.base_to),
            run.started_at.isoformat(timespec="seconds"),
        )
        for run in runs
    ]
    header = ("RUN", "BRANCH", "TRIGGER", "OUTCOME", "REASON", "BASE", "STARTED")
    return table(header, rows)


def logs_text(results: Sequence[TestResult]) -> str:
    """Each verify step's summary line followed by the tail of its output."""
    if not results:
        return "no test results"
    blocks = []
    for result in results:
        exit_code = "timed out" if result.exit_code is None else f"exit {result.exit_code}"
        summary = (
            f"== {result.step}: {result.command} ({result.outcome}, {exit_code}, "
            f"{result.attempts} attempt(s), {result.duration_s:.1f}s)"
        )
        blocks.append(f"{summary}\n{result.output_tail}".rstrip())
    return "\n".join(blocks)


def register(app: App, *, connect: Connector) -> None:
    """Add the run commands to ``app``."""

    @app.command
    async def runs(
        *,
        branch: str | None = None,
        limit: int = 20,
        settings: Annotated[Settings, Parameter(parse=False)],
    ) -> None:
        """List runs, newest first.

        Parameters
        ----------
        branch
            Only runs of this branch (name or id).
        limit
            At most this many runs.
        """
        with reported():
            async with connect(settings.target) as operations:
                found = await operations.runs.list(branch=branch, limit=limit)
        print(runs_text(found))

    @app.command
    async def show(run: str, *, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Print RUN's full report as JSON."""
        with reported():
            async with connect(settings.target) as operations:
                found = await operations.runs.get(run)
        print(found.model_dump_json(indent=2))

    @app.command
    async def diff(run: str, *, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Print RUN's rebased branch as a diff against the base it was rebased onto."""
        with reported():
            async with connect(settings.target) as operations:
                text = await operations.runs.diff(run)
        print(text, end="")

    @app.command
    async def logs(run: str, *, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Print RUN's test log: each verify step and the tail of its output."""
        with reported():
            async with connect(settings.target) as operations:
                results = await operations.runs.tests(run)
        print(logs_text(results))
