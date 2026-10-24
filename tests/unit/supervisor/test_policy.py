from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.isolation.models import IsolatedUser, SpawnErrorCode, SpawnFailed, SpawnRequest
from git_manager.runtime import ProcessUser
from git_manager.supervisor.models import (
    CapabilitiesOk,
    CapabilitiesWrong,
    CapabilitySets,
    LaunchPlan,
)
from git_manager.supervisor.policy import (
    CAP_KILL,
    check_capabilities,
    command_env,
    forbidden_env,
    is_inside,
    plan_run,
)
from tests.unit.supervisor.conftest import GM_CLAUDE, GM_TESTS, REQUIRED_MASK

CAP_DAC_OVERRIDE = 1
CAP_SYS_ADMIN = 21


def _request(
    cwd: Path, *, user: IsolatedUser = ProcessUser.TESTS, **fields: object
) -> SpawnRequest:
    return SpawnRequest.model_validate(
        {"user": user, "argv": ("just", "test"), "cwd": cwd, "env": {}} | fields
    )


def _plan(request: SpawnRequest, data_root: Path) -> LaunchPlan | SpawnFailed:
    account = GM_TESTS if request.user is ProcessUser.TESTS else GM_CLAUDE
    return plan_run(request, account, data_root=data_root, output_limit_bytes=10)


def test_a_test_command_gets_exactly_its_environment_and_its_identity(
    data_root: Path, worktree: Path
) -> None:
    env = {"PATH": "/usr/bin", "DOCKER_HOST": "tcp://localhost:2376", "GM_RUN_ID": "run-1"}
    request = _request(worktree, env=env, timeout_s=90)

    plan = _plan(request, data_root)

    assert isinstance(plan, LaunchPlan)
    assert dict(plan.env) == env | {
        "HOME": "/home/gm-tests",
        "USER": "gm-tests",
        "LOGNAME": "gm-tests",
    }
    assert plan.account == GM_TESTS
    assert plan.timeout == timedelta(seconds=90)
    assert plan.output_limit_bytes == 10


def test_the_identity_is_added_only_when_missing() -> None:
    env = command_env({"HOME": "/empty"}, account=GM_CLAUDE)

    assert env == {"HOME": "/empty", "USER": "gm-claude", "LOGNAME": "gm-claude"}


@pytest.mark.parametrize("cwd", [Path("/etc"), None])
def test_commands_run_only_inside_the_data_root(data_root: Path, cwd: Path | None) -> None:
    plan = _plan(_request(cwd or data_root), data_root)

    assert isinstance(plan, SpawnFailed)
    assert plan.code is SpawnErrorCode.INVALID_REQUEST
    assert "not inside" in plan.message


def test_a_link_out_of_the_data_root_is_outside_it(data_root: Path, tmp_path: Path) -> None:
    (data_root / "escape").symlink_to(tmp_path)

    assert not is_inside(data_root / "escape", data_root)
    assert not is_inside(data_root / "runs" / ".." / "..", data_root)
    assert is_inside(data_root / "runs" / "run-1", data_root)


@pytest.mark.parametrize(
    ("user", "name"),
    [
        (ProcessUser.TESTS, "GH_TOKEN"),
        (ProcessUser.CLAUDE, "GITHUB_TOKEN"),
        (ProcessUser.CLAUDE, "SSH_AUTH_SOCK"),
        (ProcessUser.TESTS, "GIT_SSH_COMMAND"),
        (ProcessUser.TESTS, "GM_TARGET__TOKEN"),
        (ProcessUser.CLAUDE, "GM_RUN_ID_EXTRA"),
        (ProcessUser.TESTS, "CLAUDE_CODE_OAUTH_TOKEN"),
        (ProcessUser.TESTS, "ANTHROPIC_API_KEY"),
        (ProcessUser.CLAUDE, "DOCKER_HOST"),
        (ProcessUser.CLAUDE, "DOCKER_CERT_PATH"),
    ],
)
def test_credentials_never_reach_claude_or_tests(
    data_root: Path, worktree: Path, user: IsolatedUser, name: str
) -> None:
    plan = _plan(_request(worktree, user=user, env={name: "secret"}), data_root)

    assert isinstance(plan, SpawnFailed)
    assert plan.code is SpawnErrorCode.INVALID_REQUEST
    assert name in plan.message
    assert "secret" not in plan.message


def test_claude_gets_its_token_and_tests_get_docker_and_the_run_id() -> None:
    assert forbidden_env(["CLAUDE_CODE_OAUTH_TOKEN", "GM_RUN_ID"], ProcessUser.CLAUDE) == ()
    assert forbidden_env(["DOCKER_HOST", "GM_RUN_ID"], ProcessUser.TESTS) == ()


def test_exactly_the_four_capabilities_pass() -> None:
    sets = CapabilitySets(effective=REQUIRED_MASK, bounding=REQUIRED_MASK)

    assert check_capabilities(sets) == CapabilitiesOk()


def test_docker_default_capabilities_are_too_many() -> None:
    wider = REQUIRED_MASK | 1 << CAP_DAC_OVERRIDE
    sets = CapabilitySets(effective=wider, bounding=wider | 1 << CAP_SYS_ADMIN)

    assert check_capabilities(sets) == CapabilitiesWrong(
        missing=frozenset(), extra=frozenset({CAP_DAC_OVERRIDE, CAP_SYS_ADMIN})
    )


def test_a_missing_capability_is_reported() -> None:
    sets = CapabilitySets(effective=REQUIRED_MASK & ~(1 << CAP_KILL), bounding=REQUIRED_MASK)

    assert check_capabilities(sets) == CapabilitiesWrong(missing=frozenset({CAP_KILL}))
