from git_manager.branches.runs import QueuedRun
from git_manager.rebasing.models import RunTrigger
from tests.conftest import START


def test_queued_run_is_an_immutable_value() -> None:
    run = QueuedRun("b", RunTrigger.POLL, START)

    assert run == QueuedRun(branch_id="b", trigger=RunTrigger.POLL, queued_at=START)
    assert hash(run) == hash(QueuedRun("b", RunTrigger.POLL, START))
