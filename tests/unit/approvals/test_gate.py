from git_manager.approvals.gate import UnrecordedApprovalGate
from git_manager.approvals.protocols import ApprovalGate
from git_manager.branches import BranchHeads
from tests.conftest import SequentialIds, sha


async def test_issues_a_new_id_per_request() -> None:
    gate: ApprovalGate = UnrecordedApprovalGate(SequentialIds(prefix="approval"))
    heads = [BranchHeads(branch="feature/one", old_head=sha(2), new_head=sha(4))]

    first = await gate.request(run_id="run-1", base_sha=sha(3), heads=heads)
    second = await gate.request(run_id="run-2", base_sha=sha(3), heads=heads)

    assert (first, second) == ("approval-1", "approval-2")
