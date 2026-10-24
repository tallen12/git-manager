from pathlib import Path

from git_manager.isolation import SpawnCompleted, SpawnRequest, SupervisorChannel
from git_manager.runtime import ProcessUser
from tests.unit.isolation.conftest import FakeSupervisorChannel


async def test_fake_channel_records_requests_and_exits_zero_by_default(
    channel: FakeSupervisorChannel,
) -> None:
    contract: SupervisorChannel = channel
    request = SpawnRequest(user=ProcessUser.TESTS, argv=("true",), cwd=Path.cwd(), env={})

    response = await contract.spawn(request)

    assert response == SpawnCompleted(exit_code=0, stdout="", stderr="", duration_s=0)
    assert channel.requests == [request]
