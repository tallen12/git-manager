import asyncio

from git_manager.rebasing import BranchLocks
from git_manager.rebasing.locks import InMemoryBranchLocks


async def test_a_second_holder_waits_until_the_first_leaves() -> None:
    locks = InMemoryBranchLocks()
    contract: BranchLocks = locks
    order: list[str] = []

    async def second() -> None:
        async with contract.hold("branch-1"):
            order.append("second")

    async with contract.hold("branch-1"):
        task = asyncio.create_task(second())
        await asyncio.sleep(0)
        order.append("first")
        assert locks.held("branch-1")
    await task

    assert order == ["first", "second"]
    assert not locks.held("branch-1")


async def test_different_branches_do_not_block_each_other() -> None:
    locks = InMemoryBranchLocks()

    async with locks.hold("branch-1"), locks.hold("branch-2"):
        assert locks.held("branch-1")
        assert locks.held("branch-2")


async def test_the_lock_is_released_when_the_block_raises() -> None:
    locks = InMemoryBranchLocks()

    try:
        async with locks.hold("branch-1"):
            raise ValueError
    except ValueError:
        pass

    assert not locks.held("branch-1")
