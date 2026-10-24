import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.branches import BranchState
from git_manager.branches.daemon import DEFAULT_TICK, AsyncioSleeper, Daemon
from git_manager.branches.poller import Poller
from git_manager.branches.queue import FifoRunQueue
from git_manager.config.errors import ConfigError
from git_manager.config.models import (
    BranchOptions,
    CadenceConfig,
    CadenceMode,
    RepoConfig,
    RepoSection,
    VerifyConfig,
)
from git_manager.errors import NotFoundError
from git_manager.events import EventKind
from git_manager.rebasing.errors import GitError
from git_manager.rebasing.models import RebaseCompleted, RunTrigger
from tests.conftest import (
    FakeGit,
    FixedClock,
    InMemoryBranches,
    RecordingEventSink,
    make_branch,
    sha,
)
from tests.unit.branches.conftest import (
    FakeSleeper,
    ScriptedExecutor,
    StaticConfig,
    wait_until,
)
from tests.unit.rebasing.conftest import NEW_BASE, REBASED, make_harness

OLD_BASE, HEAD, MOVED_BASE = sha(1), sha(2), sha(3)


def immediate(data_dir: Path = Path("data")) -> RepoConfig:
    return RepoConfig(
        repo=RepoSection(url="https://example.com/repo.git", data_dir=data_dir),
        defaults=BranchOptions(
            cadence=CadenceConfig(mode=CadenceMode.IMMEDIATE),
            verify=VerifyConfig(test="just test"),
        ),
    )


@dataclass(slots=True)
class FailingRemote:
    """``RemoteRefs`` whose remote cannot be reached."""

    calls: int = 0

    async def ls_remote(self, refs: object) -> dict[str, str]:
        self.calls += 1
        raise GitError(argv=["git", "ls-remote"], exit_code=128, stderr="unreachable")


@dataclass(slots=True)
class Rig:
    """A daemon over the real poller and queue, with fakes around them."""

    daemon: Daemon
    remote: FakeGit
    branches: InMemoryBranches
    queue: FifoRunQueue
    executor: ScriptedExecutor
    config: StaticConfig
    sleeper: FakeSleeper
    events: RecordingEventSink


@pytest.fixture
def rig(clock: FixedClock) -> Rig:
    remote = FakeGit(remote={"main": OLD_BASE, "feature/one": HEAD, "feature/two": sha(5)})
    branches = InMemoryBranches()
    branches.rows["branch-1"] = make_branch()
    branches.rows["branch-2"] = make_branch(id="branch-2", name="feature/two", last_head_sha=sha(5))
    events = RecordingEventSink(clock=clock)
    queue = FifoRunQueue(clock=clock)
    executor = ScriptedExecutor()
    config = StaticConfig(immediate())
    sleeper = FakeSleeper(clock)
    poller = Poller(git=remote, branches=branches, events=events, queue=queue, clock=clock)
    daemon = Daemon(
        poller=poller,
        queue=queue,
        executor=executor,
        config=config,
        branches=branches,
        sleeper=sleeper,
    )
    return Rig(daemon, remote, branches, queue, executor, config, sleeper, events)


async def stopped(rig: Rig, task: asyncio.Task[None]) -> None:
    rig.daemon.stop()
    await asyncio.wait_for(task, timeout=5)


async def test_polls_every_tick_until_stopped(rig: Rig) -> None:
    task = asyncio.create_task(rig.daemon.run())
    await wait_until(lambda: len(rig.sleeper.slept) >= 3)

    await stopped(rig, task)

    assert set(rig.sleeper.slept) == {DEFAULT_TICK}
    ticks = len(rig.sleeper.slept)
    await asyncio.sleep(0)
    assert len(rig.sleeper.slept) == ticks


async def test_base_change_is_run_through_the_executor(rig: Rig) -> None:
    rig.remote.remote["main"] = MOVED_BASE
    task = asyncio.create_task(rig.daemon.run())

    await wait_until(lambda: len(rig.executor.finished) == 2)
    await stopped(rig, task)

    assert rig.executor.started == [
        ("branch-1", RunTrigger.POLL),
        ("branch-2", RunTrigger.POLL),
    ]


async def test_runs_one_at_a_time_while_polling_goes_on(rig: Rig) -> None:
    rig.executor.hold = True
    rig.remote.remote["main"] = MOVED_BASE
    task = asyncio.create_task(rig.daemon.run())
    await wait_until(lambda: len(rig.executor.started) == 1)
    ticks = len(rig.sleeper.slept)

    await wait_until(lambda: len(rig.sleeper.slept) > ticks + 120)

    # Two minutes of polls later, the first run still blocks the second.
    assert rig.executor.started == [("branch-1", RunTrigger.POLL)]
    assert [run.branch_id for run in rig.queue.waiting()] == ["branch-2"]
    rig.executor.release.set()
    await wait_until(lambda: len(rig.executor.finished) == 2)
    assert rig.executor.most_at_once == 1
    await stopped(rig, task)


async def test_stop_lets_the_current_run_finish_before_returning(rig: Rig) -> None:
    rig.executor.hold = True
    rig.remote.remote["main"] = MOVED_BASE
    task = asyncio.create_task(rig.daemon.run())
    await wait_until(lambda: len(rig.executor.started) == 1)

    rig.daemon.stop()
    for _ in range(100):
        await asyncio.sleep(0)
    assert not task.done()
    ticks = len(rig.sleeper.slept)

    rig.executor.release.set()
    await asyncio.wait_for(task, timeout=5)

    assert rig.executor.finished == ["branch-1"]
    # The waiting run is not started; its branch stays scheduled for the next start.
    assert rig.branches.rows["branch-2"].state is BranchState.SCHEDULED
    assert len(rig.sleeper.slept) == ticks


async def test_stop_while_idle_returns_without_a_run(rig: Rig) -> None:
    task = asyncio.create_task(rig.daemon.run())
    await wait_until(lambda: len(rig.sleeper.slept) >= 1)

    await stopped(rig, task)

    assert rig.executor.started == []


async def test_branches_left_scheduled_are_queued_again_on_start(rig: Rig) -> None:
    # As a previous daemon left it: scheduled, but its in-memory queue is gone.
    rig.remote.remote["main"] = MOVED_BASE
    rig.branches.rows["branch-1"] = make_branch(state=BranchState.SCHEDULED)
    rig.config.config = immediate().model_copy(
        update={"defaults": BranchOptions(cadence=CadenceConfig(mode=CadenceMode.MANUAL))}
    )
    task = asyncio.create_task(rig.daemon.run())

    await wait_until(lambda: len(rig.executor.finished) == 1)
    await stopped(rig, task)

    assert rig.executor.started == [("branch-1", RunTrigger.POLL)]


async def test_a_failing_run_does_not_stop_the_worker(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    rig.executor.fail_with = RuntimeError("boom")
    rig.remote.remote["main"] = MOVED_BASE
    task = asyncio.create_task(rig.daemon.run())

    with caplog.at_level(logging.ERROR):
        await wait_until(lambda: len(rig.executor.started) == 2)
    await stopped(rig, task)

    assert [record.getMessage() for record in caplog.records] == [
        "run of branch-1 failed",
        "run of branch-2 failed",
    ]


async def test_a_branch_untracked_while_queued_is_skipped(rig: Rig) -> None:
    rig.executor.fail_with = NotFoundError(kind="branch", key="branch-1")
    rig.remote.remote["main"] = MOVED_BASE
    task = asyncio.create_task(rig.daemon.run())

    await wait_until(lambda: len(rig.executor.started) == 2)
    await stopped(rig, task)

    assert rig.executor.finished == []


async def test_poll_errors_are_logged_and_polling_goes_on(
    rig: Rig, clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    remote = FailingRemote()
    daemon = Daemon(
        poller=Poller(
            git=remote,
            branches=rig.branches,
            events=rig.events,
            queue=rig.queue,
            clock=clock,
        ),
        queue=rig.queue,
        executor=rig.executor,
        config=rig.config,
        branches=rig.branches,
        sleeper=rig.sleeper,
    )
    task = asyncio.create_task(daemon.run())

    with caplog.at_level(logging.WARNING):
        # Each branch is retried once its poll interval has passed again.
        await wait_until(lambda: remote.calls >= 2)
    daemon.stop()
    await asyncio.wait_for(task, timeout=5)

    assert caplog.records[0].getMessage().startswith("poll failed: git ls-remote exited 128")


async def test_config_errors_are_logged_and_polling_goes_on(rig: Rig) -> None:
    rig.config.error = ConfigError("config.yaml", ["defaults.cadence.mode: invalid"])
    task = asyncio.create_task(rig.daemon.run())

    await wait_until(lambda: len(rig.sleeper.slept) >= 3)
    await stopped(rig, task)

    assert rig.executor.started == []


async def test_own_push_is_not_reported_as_a_human_push(clock: FixedClock, tmp_path: Path) -> None:
    harness = make_harness(tmp_path / "data")
    # The poller first sees the branch on its old base, then the base moves.
    harness.git.remote["main"] = OLD_BASE
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))
    queue = FifoRunQueue(clock=clock)
    sleeper = FakeSleeper(clock)
    daemon = Daemon(
        poller=Poller(
            git=harness.git,
            branches=harness.branches,
            events=harness.events,
            queue=queue,
            clock=clock,
        ),
        queue=queue,
        executor=harness.runner,
        config=StaticConfig(immediate(harness.data_dir)),
        branches=harness.branches,
        sleeper=sleeper,
    )
    task = asyncio.create_task(daemon.run())
    await wait_until(lambda: len(sleeper.slept) >= 1)

    harness.git.remote["main"] = NEW_BASE
    await wait_until(lambda: harness.git.remote["feature/one"] == REBASED)
    # Let the poller look at the pushed branch a few times.
    await wait_until(lambda: len(sleeper.slept) >= 300)
    daemon.stop()
    await asyncio.wait_for(task, timeout=5)

    kinds = [event.kind for event in harness.events.events]
    assert EventKind.HEAD_MOVED not in kinds
    assert EventKind.RUN_FINISHED in kinds
    assert harness.branches.rows["branch-1"].state is BranchState.IDLE


async def test_human_push_after_own_push_is_reported(clock: FixedClock, tmp_path: Path) -> None:
    harness = make_harness(tmp_path / "data")
    harness.git.remote["main"] = OLD_BASE
    harness.git.rebase_outcomes.append(RebaseCompleted(head=REBASED))
    queue = FifoRunQueue(clock=clock)
    sleeper = FakeSleeper(clock)
    daemon = Daemon(
        poller=Poller(
            git=harness.git,
            branches=harness.branches,
            events=harness.events,
            queue=queue,
            clock=clock,
        ),
        queue=queue,
        executor=harness.runner,
        config=StaticConfig(immediate(harness.data_dir)),
        branches=harness.branches,
        sleeper=sleeper,
    )
    task = asyncio.create_task(daemon.run())
    await wait_until(lambda: len(sleeper.slept) >= 1)
    harness.git.remote["main"] = NEW_BASE
    await wait_until(lambda: harness.git.remote["feature/one"] == REBASED)
    await wait_until(lambda: len(sleeper.slept) >= 300)

    harness.git.remote["feature/one"] = sha(9)
    await wait_until(
        lambda: any(event.kind is EventKind.HEAD_MOVED for event in harness.events.events)
    )
    daemon.stop()
    await asyncio.wait_for(task, timeout=5)

    moved = [event for event in harness.events.events if event.kind is EventKind.HEAD_MOVED]
    assert [event.data for event in moved] == [{"from": REBASED, "to": sha(9)}]


async def test_asyncio_sleeper_waits_on_the_event_loop() -> None:
    await asyncio.wait_for(AsyncioSleeper().sleep(timedelta(0)), timeout=1)


async def test_a_branch_paused_while_queued_is_skipped(
    clock: FixedClock, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The real runner, so the check is the one made under the branch lock.
    harness = make_harness(tmp_path / "data")
    branch = harness.branches.rows["branch-1"]
    queue = FifoRunQueue(clock=clock)
    # Queued by a poll, then paused by a human before the worker reached it.
    queue.put(branch.id, trigger=RunTrigger.POLL)
    harness.branches.rows[branch.id] = branch.model_copy(update={"state": BranchState.PAUSED})
    sleeper = FakeSleeper(clock)
    daemon = Daemon(
        poller=Poller(
            git=harness.git,
            branches=harness.branches,
            events=harness.events,
            queue=queue,
            clock=clock,
        ),
        queue=queue,
        executor=harness.runner,
        config=StaticConfig(immediate(harness.data_dir)),
        branches=harness.branches,
        sleeper=sleeper,
    )
    task = asyncio.create_task(daemon.run())

    with caplog.at_level(logging.INFO):
        await wait_until(lambda: any("it is paused" in r.getMessage() for r in caplog.records))
    daemon.stop()
    await asyncio.wait_for(task, timeout=5)

    assert harness.runs.rows == {}
    assert harness.git.fetched == []
    assert harness.branches.rows[branch.id].state is BranchState.PAUSED
