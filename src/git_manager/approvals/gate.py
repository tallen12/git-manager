"""The approval gate until approvals are recorded (M3)."""

from collections.abc import Sequence

from git_manager.branches.models import BranchHeads
from git_manager.runtime.protocols import IdGenerator


class UnrecordedApprovalGate:
    """``ApprovalGate`` that only stops the run in ``awaiting_approval``.

    M1 records no approval, so nothing can approve the result: syncing the branch again
    starts a new run. F19 replaces this with the real gate.
    """

    def __init__(self, ids: IdGenerator) -> None:
        self._ids = ids

    async def request(self, *, run_id: str, base_sha: str, heads: Sequence[BranchHeads]) -> str:
        return self._ids.new_id()
