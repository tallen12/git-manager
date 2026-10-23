from git_manager.branches.protocols import BranchOperations
from git_manager.core.unavailable import UnavailableBranches


def test_unavailable_branches_satisfy_the_protocol() -> None:
    # The annotation is the contract: the type checker rejects a non-conforming class.
    operations: BranchOperations = UnavailableBranches("later")

    assert operations is not None
