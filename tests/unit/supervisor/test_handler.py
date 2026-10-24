import errno
from pathlib import Path

import pytest

from git_manager.isolation.models import (
    Chowned,
    ChownErrorCode,
    ChownFailed,
    ChownRequest,
    SpawnCompleted,
    SpawnErrorCode,
    SpawnFailed,
    SpawnRequest,
)
from git_manager.runtime import ProcessUser
from git_manager.supervisor.handler import RequestHandler
from git_manager.supervisor.settings import SupervisorSettings
from tests.unit.supervisor.conftest import (
    GM,
    GM_CLAUDE,
    GM_TESTS,
    FakeAccounts,
    FakeLauncher,
    OwnershipCall,
    RecordingOwnership,
)


def _spawn(
    *, argv: tuple[str, ...], cwd: Path, user: ProcessUser, **fields: object
) -> SpawnRequest:
    return SpawnRequest.model_validate({"argv": argv, "cwd": cwd, "user": user, "env": {}} | fields)


@pytest.fixture
def launcher() -> FakeLauncher:
    return FakeLauncher()


@pytest.fixture
def ownership() -> RecordingOwnership:
    return RecordingOwnership()


@pytest.fixture
def handler(
    supervisor_settings: SupervisorSettings,
    launcher: FakeLauncher,
    ownership: RecordingOwnership,
) -> RequestHandler:
    return RequestHandler(
        settings=supervisor_settings,
        accounts=FakeAccounts(),
        ownership=ownership,
        launcher=launcher,
    )


async def test_the_daemon_runs_a_test_command_as_gm_tests(
    handler: RequestHandler, launcher: FakeLauncher, worktree: Path
) -> None:
    request = _spawn(argv=("just", "test"), cwd=worktree, user=ProcessUser.TESTS)

    reply = await handler.handle(request, peer_uid=GM.uid)

    assert reply == SpawnCompleted(exit_code=0, stdout="", stderr="", duration_s=0)
    [plan] = launcher.plans
    assert plan.account == GM_TESTS
    assert plan.argv == ("just", "test")
    assert plan.output_limit_bytes == 1024


@pytest.mark.parametrize("peer", [GM_CLAUDE.uid, GM_TESTS.uid, 0])
async def test_only_the_daemon_may_ask(
    handler: RequestHandler, launcher: FakeLauncher, worktree: Path, peer: int
) -> None:
    request = _spawn(argv=("id",), cwd=worktree, user=ProcessUser.CLAUDE)

    reply = await handler.handle(request, peer_uid=peer)

    assert isinstance(reply, SpawnFailed)
    assert reply.code is SpawnErrorCode.INVALID_REQUEST
    assert "only gm" in reply.message
    assert launcher.plans == []


async def test_a_user_missing_from_the_image_is_reported(
    supervisor_settings: SupervisorSettings, worktree: Path
) -> None:
    accounts = FakeAccounts()
    del accounts.users["gm-claude"]
    handler = RequestHandler(
        settings=supervisor_settings,
        accounts=accounts,
        ownership=RecordingOwnership(),
        launcher=FakeLauncher(),
    )

    reply = await handler.handle(
        _spawn(argv=("claude",), cwd=worktree, user=ProcessUser.CLAUDE), peer_uid=GM.uid
    )

    assert isinstance(reply, SpawnFailed)
    assert reply.message == "no such user gm-claude"


async def test_a_policy_violation_never_reaches_the_launcher(
    handler: RequestHandler, launcher: FakeLauncher, worktree: Path
) -> None:
    request = _spawn(
        argv=("just", "test"), cwd=worktree, env={"GH_TOKEN": "t"}, user=ProcessUser.TESTS
    )

    reply = await handler.handle(request, peer_uid=GM.uid)

    assert isinstance(reply, SpawnFailed)
    assert reply.code is SpawnErrorCode.INVALID_REQUEST
    assert launcher.plans == []


async def test_a_worktree_is_handed_to_claude(
    handler: RequestHandler, ownership: RecordingOwnership, worktree: Path
) -> None:
    reply = await handler.handle(
        ChownRequest(path=worktree, user=ProcessUser.CLAUDE), peer_uid=GM.uid
    )

    assert reply == Chowned()
    assert ownership.calls == [OwnershipCall("hand_over", worktree, GM_CLAUDE.uid, GM_CLAUDE.gid)]


async def test_a_worktree_goes_back_to_the_daemon(
    handler: RequestHandler, ownership: RecordingOwnership, worktree: Path
) -> None:
    reply = await handler.handle(
        ChownRequest(path=worktree, user=ProcessUser.ORCHESTRATOR), peer_uid=GM.uid
    )

    assert reply == Chowned()
    assert ownership.calls[0].uid == GM.uid


@pytest.mark.parametrize("path", [Path("/run/secrets"), Path("/etc")])
async def test_nothing_outside_the_data_root_changes_owner(
    handler: RequestHandler, ownership: RecordingOwnership, path: Path
) -> None:
    reply = await handler.handle(ChownRequest(path=path, user=ProcessUser.TESTS), peer_uid=GM.uid)

    assert isinstance(reply, ChownFailed)
    assert reply.code is ChownErrorCode.INVALID_REQUEST
    assert ownership.calls == []


async def test_the_data_root_itself_is_never_handed_over(
    handler: RequestHandler, data_root: Path
) -> None:
    reply = await handler.handle(
        ChownRequest(path=data_root, user=ProcessUser.TESTS), peer_uid=GM.uid
    )

    assert isinstance(reply, ChownFailed)
    assert reply.code is ChownErrorCode.INVALID_REQUEST


async def test_hard_linked_files_are_reported_as_skipped(
    handler: RequestHandler, ownership: RecordingOwnership, worktree: Path
) -> None:
    ownership.skipped = (Path("sub/linked"),)

    reply = await handler.handle(
        ChownRequest(path=worktree, user=ProcessUser.CLAUDE), peer_uid=GM.uid
    )

    assert reply == Chowned(skipped=(Path("sub/linked"),))


async def test_a_failed_chown_reports_the_os_error(
    handler: RequestHandler, ownership: RecordingOwnership, worktree: Path
) -> None:
    ownership.failures[worktree] = PermissionError(errno.EPERM, "Operation not permitted")

    reply = await handler.handle(
        ChownRequest(path=worktree, user=ProcessUser.TESTS), peer_uid=GM.uid
    )

    assert reply == ChownFailed(
        code=ChownErrorCode.FAILED, message="[Errno 1] Operation not permitted"
    )


async def test_a_stranger_cannot_hand_over_a_tree(
    handler: RequestHandler, ownership: RecordingOwnership, worktree: Path
) -> None:
    reply = await handler.handle(
        ChownRequest(path=worktree, user=ProcessUser.CLAUDE), peer_uid=GM_CLAUDE.uid
    )

    assert isinstance(reply, ChownFailed)
    assert reply.code is ChownErrorCode.INVALID_REQUEST
    assert ownership.calls == []
