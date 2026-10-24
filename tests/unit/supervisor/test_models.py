from datetime import timedelta
from pathlib import Path

import pytest

from git_manager.supervisor.models import (
    Account,
    CapabilitiesWrong,
    LaunchPlan,
    OwnershipModes,
)


def _plan(env: dict[str, str]) -> LaunchPlan:
    return LaunchPlan(
        argv=("true",),
        cwd=Path("/data"),
        env=env,
        account=Account(name="gm-tests", uid=1, gid=1, groups=(), home=Path("/home")),
        timeout=timedelta(minutes=1),
        stdin=None,
        output_limit_bytes=1,
    )


def test_a_launch_plan_keeps_a_read_only_environment() -> None:
    env = {"PATH": "/bin"}
    plan = _plan(env)
    env["GH_TOKEN"] = "secret"

    assert dict(plan.env) == {"PATH": "/bin"}
    with pytest.raises(TypeError):
        plan.env["X"] = "y"  # ty: ignore[invalid-assignment] -- proving it is read-only


def test_ownership_modes_keep_existing_modes_by_default() -> None:
    assert OwnershipModes() == OwnershipModes(directory=None, file=None)


def test_wrong_capabilities_default_to_nothing_extra() -> None:
    assert CapabilitiesWrong(missing=frozenset({5})).extra == frozenset()
