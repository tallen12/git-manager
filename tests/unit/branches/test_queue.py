import asyncio
from datetime import timedelta

import pytest

from git_manager.branches.protocols import RunQueue
from git_manager.branches.queue import FifoRunQueue
from git_manager.rebasing.models import RunTrigger
from tests.conftest import START, FixedClock


@pytest.fixture
def queue(clock: FixedClock) -> FifoRunQueue:
    return FifoRunQueue(clock=clock)


def test_put_queues_once_per_branch_in_order(queue: FifoRunQueue, clock: FixedClock) -> None:
    contract: RunQueue = queue
    assert contract.put("a", trigger=RunTrigger.POLL)
    clock.advance(timedelta(seconds=1))
    assert contract.put("b", trigger=RunTrigger.MANUAL)
    assert not contract.put("a", trigger=RunTrigger.MANUAL)

    assert [(run.branch_id, run.trigger, run.queued_at) for run in contract.waiting()] == [
        ("a", RunTrigger.POLL, START),
        ("b", RunTrigger.MANUAL, START + timedelta(seconds=1)),
    ]


def test_discard_removes_a_waiting_run(queue: FifoRunQueue) -> None:
    queue.put("a", trigger=RunTrigger.POLL)

    assert queue.discard("a")
    assert not queue.discard("a")
    assert queue.waiting() == ()


async def test_take_hands_out_runs_first_in_first_out(queue: FifoRunQueue) -> None:
    queue.put("a", trigger=RunTrigger.POLL)
    queue.put("b", trigger=RunTrigger.POLL)

    async with queue.take() as first:
        assert queue.active == first
    async with queue.take() as second:
        pass

    assert (first.branch_id, second.branch_id) == ("a", "b")
    assert queue.active is None


async def test_one_run_at_a_time(queue: FifoRunQueue) -> None:
    queue.put("a", trigger=RunTrigger.POLL)
    queue.put("b", trigger=RunTrigger.POLL)
    started: list[str] = []
    release = asyncio.Event()

    async def worker() -> None:
        async with queue.take() as run:
            started.append(run.branch_id)
            await release.wait()

    tasks = [asyncio.create_task(worker()), asyncio.create_task(worker())]
    await asyncio.sleep(0.01)
    assert started == ["a"]
    release.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
    assert started == ["a", "b"]


async def test_take_waits_for_a_run_to_be_queued(queue: FifoRunQueue) -> None:
    async def take_one() -> str:
        async with queue.take() as run:
            return run.branch_id

    task = asyncio.create_task(take_one())
    await asyncio.sleep(0.01)
    assert not task.done()
    queue.put("late", trigger=RunTrigger.POLL)

    assert await asyncio.wait_for(task, timeout=1) == "late"


async def test_a_failed_run_frees_the_queue(queue: FifoRunQueue) -> None:
    queue.put("a", trigger=RunTrigger.POLL)
    queue.put("b", trigger=RunTrigger.POLL)

    with pytest.raises(RuntimeError):
        async with queue.take():
            raise RuntimeError

    async with asyncio.timeout(1), queue.take() as run:
        assert run.branch_id == "b"


async def test_a_running_branch_may_queue_again(queue: FifoRunQueue) -> None:
    queue.put("a", trigger=RunTrigger.POLL)

    async with queue.take():
        assert queue.put("a", trigger=RunTrigger.POLL)

    assert [run.branch_id for run in queue.waiting()] == ["a"]
