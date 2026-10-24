"""Approval contracts."""

from collections.abc import Sequence
from typing import Protocol

from git_manager.branches.models import BranchHeads


class ApprovalGate(Protocol):
    """Holds a verified result until a human approves it.

    M1 only stops runs here (``approval_policy: always``); approving, rejecting and the
    stale check arrive with the approvals feature in M3.
    """

    async def request(self, *, run_id: str, base_sha: str, heads: Sequence[BranchHeads]) -> str:
        """Record a pending approval bound to ``base_sha`` and ``heads``; return its id."""
        ...
