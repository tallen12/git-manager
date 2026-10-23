from collections.abc import Awaitable, Callable

import pytest

from git_manager.core import UnavailableError
from git_manager.core.unavailable import UnavailableBranches, UnavailableConfig, UnavailableRuns

BRANCHES = UnavailableBranches("lands in M1")
RUNS = UnavailableRuns("lands in M1")


@pytest.mark.parametrize(
    ("call", "operation"),
    [
        (UnavailableConfig("lands in M1").show, "config show"),
        (BRANCHES.status, "status"),
        (lambda: BRANCHES.track(name="f", base="main"), "track"),
        (lambda: BRANCHES.untrack("f"), "untrack"),
        (lambda: BRANCHES.sync("f"), "sync"),
        (lambda: BRANCHES.pause("f"), "pause"),
        (lambda: BRANCHES.resume("f"), "resume"),
        (RUNS.list, "runs"),
        (lambda: RUNS.get("r"), "show"),
        (lambda: RUNS.diff("r"), "diff"),
        (lambda: RUNS.tests("r"), "logs"),
    ],
)
async def test_every_operation_raises_with_its_cli_name_and_reason(
    call: Callable[[], Awaitable[object]], operation: str
) -> None:
    with pytest.raises(UnavailableError) as raised:
        await call()

    assert raised.value.operation == operation
    assert raised.value.reason == "lands in M1"
