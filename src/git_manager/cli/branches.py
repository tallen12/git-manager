"""Branch commands: ``status``, ``track``, ``untrack``, ``sync``, ``pause`` and ``resume``."""

import sys
from typing import Annotated, assert_never

from cyclopts import App, Parameter

from git_manager.branches.models import BranchState, RepoStatus, TrackedBranch
from git_manager.branches.results import SyncCompleted, SyncOutcome, SyncQueued
from git_manager.cli.output import EXIT_NOT_PUSHED, reported, short, table
from git_manager.core import Connector, Settings


def branch_line(branch: TrackedBranch) -> str:
    """One branch with its state and reason: ``feature/x on main: paused (paused_by_user)``."""
    reason = "" if branch.reason is None else f" ({branch.reason})"
    return f"{branch.name} on {branch.base}: {branch.state}{reason}"


def status_text(status: RepoStatus) -> str:
    """The repository and a table of its tracked branches."""
    if not status.branches:
        return f"repo {status.url}\nno tracked branches"
    rows = [
        (b.name, b.base, str(b.state), b.reason or "", short(b.last_head_sha), short(b.fork_point))
        for b in status.branches
    ]
    header = ("BRANCH", "BASE", "STATE", "REASON", "HEAD", "FORK POINT")
    return f"repo {status.url}\n{table(header, rows)}"


def sync_text(outcome: SyncOutcome) -> str:
    """What a sync did: the finished run, or where it waits in the daemon's queue."""
    match outcome:
        case SyncCompleted(run=run):
            heads = run.heads[0]
            reason = "" if run.reason is None else f" ({run.reason})"
            return (
                f"run {run.id}: {run.outcome}{reason}\n"
                f"{heads.branch} {short(heads.old_head)} -> {short(heads.new_head)}"
                f" on {short(run.base_to)}"
            )
        case SyncQueued(branch_id=branch_id, position=position):
            return f"queued {branch_id} behind {position} other run(s)"
        case _:
            assert_never(outcome)


def sync_pushed(outcome: SyncOutcome) -> bool:
    """Whether the outcome needs no attention: pushed (idle), or left to the daemon."""
    match outcome:
        case SyncCompleted(run=run):
            return run.outcome is BranchState.IDLE
        case SyncQueued():
            return True
        case _:
            assert_never(outcome)


def register(app: App, *, connect: Connector) -> None:
    """Add the branch commands to ``app``."""

    @app.command
    async def status(*, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """List the tracked branches with their states."""
        with reported():
            async with connect(settings.target) as operations:
                repo = await operations.branches.status()
        print(status_text(repo))

    @app.command
    async def track(
        branch: str, *, base: str, settings: Annotated[Settings, Parameter(parse=False)]
    ) -> None:
        """Keep BRANCH rebased on --base, starting from their merge-base.

        Parameters
        ----------
        branch
            The remote branch to track.
        base
            The branch it is rebased onto.
        """
        with reported():
            async with connect(settings.target) as operations:
                tracked = await operations.branches.track(name=branch, base=base)
        print(f"tracked {branch_line(tracked)}, fork point {short(tracked.fork_point)}")

    @app.command
    async def untrack(
        branch: str, *, settings: Annotated[Settings, Parameter(parse=False)]
    ) -> None:
        """Stop tracking BRANCH (name or id); its runs stay in the history."""
        with reported():
            async with connect(settings.target) as operations:
                await operations.branches.untrack(branch)
        print(f"untracked {branch}")

    @app.command
    async def sync(branch: str, *, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Rebase BRANCH now, whatever its cadence; local mode waits for the run to end.

        Exits 3 if the run ended without pushing.
        """
        with reported():
            async with connect(settings.target) as operations:
                outcome = await operations.branches.sync(branch)
        print(sync_text(outcome))
        if not sync_pushed(outcome):
            sys.exit(EXIT_NOT_PUSHED)

    @app.command
    async def pause(branch: str, *, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Stop polling and syncing BRANCH without losing its state."""
        with reported():
            async with connect(settings.target) as operations:
                paused = await operations.branches.pause(branch)
        print(branch_line(paused))

    @app.command
    async def resume(branch: str, *, settings: Annotated[Settings, Parameter(parse=False)]) -> None:
        """Poll BRANCH again after pause, or once you settled it from needs_human or
        diverged_remote; it continues from the remote branch as it is now."""
        with reported():
            async with connect(settings.target) as operations:
                resumed = await operations.branches.resume(branch)
        print(branch_line(resumed))
