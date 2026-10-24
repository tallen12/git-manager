from git_manager.approvals import ApprovalGate
from git_manager.branches import BranchHeads
from tests.conftest import RecordingApprovalGate, sha


async def test_recording_gate_binds_each_request_to_base_and_heads() -> None:
    fake = RecordingApprovalGate()
    gate: ApprovalGate = fake
    heads = [BranchHeads(branch="feature/one", old_head=sha(2), new_head=sha(4))]

    first = await gate.request(run_id="run-1", base_sha=sha(3), heads=heads)
    second = await gate.request(run_id="run-2", base_sha=sha(5), heads=heads)

    assert (first, second) == ("approval-1", "approval-2")
    assert fake.requests[0].base_sha == sha(3)
    assert fake.requests[0].heads == tuple(heads)
