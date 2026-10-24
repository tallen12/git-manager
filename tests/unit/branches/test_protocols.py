from git_manager.branches.protocols import BranchOperations, RemoteRefs, RunQueue, RunScheduler
from git_manager.branches.queue import FifoRunQueue
from git_manager.core.unavailable import UnavailableBranches
from tests.conftest import FakeGit, FixedClock


def test_unavailable_branches_satisfy_the_protocol() -> None:
    # The annotation is the contract: the type checker rejects a non-conforming class.
    operations: BranchOperations = UnavailableBranches("later")

    assert operations is not None


def test_fifo_queue_is_a_run_queue_and_scheduler() -> None:
    queue: RunQueue = FifoRunQueue(clock=FixedClock())
    scheduler: RunScheduler = queue

    assert scheduler is queue


def test_git_provides_remote_refs() -> None:
    refs: RemoteRefs = FakeGit()

    assert refs is not None
