import asyncio

from git_manager.supervisor.server import unless_peer_leaves


async def test_work_finishes_while_the_peer_waits() -> None:
    async def work() -> str:
        return "reply"

    assert await unless_peer_leaves(work(), asyncio.StreamReader()) == "reply"


async def test_work_is_cancelled_when_the_peer_closes_its_end() -> None:
    cancelled = asyncio.Event()

    async def work() -> str:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "never"

    reader = asyncio.StreamReader()
    reader.feed_eof()

    assert await unless_peer_leaves(work(), reader) is None
    assert cancelled.is_set()
