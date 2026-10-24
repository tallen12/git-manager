"""What the supervisor allows: paths, environments and its own capabilities."""

from collections.abc import Iterable, Mapping
from datetime import timedelta
from pathlib import Path

from git_manager.isolation.models import IsolatedUser, SpawnErrorCode, SpawnFailed, SpawnRequest
from git_manager.runtime import ProcessUser
from git_manager.supervisor.models import (
    Account,
    CapabilitiesOk,
    CapabilitiesWrong,
    CapabilityCheck,
    CapabilitySets,
    LaunchPlan,
)

# Capability numbers from linux/capability.h.
CAP_CHOWN = 0
CAP_KILL = 5
CAP_SETGID = 6
CAP_SETUID = 7
REQUIRED_CAPABILITIES = frozenset({CAP_CHOWN, CAP_KILL, CAP_SETGID, CAP_SETUID})

# Git, GitHub and Git Manager credentials stay with the daemon (Security rules in the spec).
# The daemon already scrubs its environment; refusing these here catches a caller that
# passes one on purpose.
_CREDENTIAL_ENV = frozenset(
    {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SSH_AUTH_SOCK",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
    }
)
# Git Manager's own settings (tokens among them) start with GM_; the run id is for tests.
_SETTINGS_PREFIX = "GM_"
_PASSED_SETTINGS = frozenset({"GM_RUN_ID"})
_CLAUDE_ENV = frozenset({"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"})
# Docker access is effectively root; only the test step gets it.
_DOCKER_PREFIX = "DOCKER_"


def forbidden_env(names: Iterable[str], user: IsolatedUser) -> tuple[str, ...]:
    """The names in ``names`` that must never reach a command run as ``user``, sorted."""

    def forbidden(name: str) -> bool:
        if name in _CREDENTIAL_ENV:
            return True
        if name.startswith(_SETTINGS_PREFIX) and name not in _PASSED_SETTINGS:
            return True
        match user:
            case ProcessUser.TESTS:
                return name in _CLAUDE_ENV
            case ProcessUser.CLAUDE:
                return name.startswith(_DOCKER_PREFIX)

    return tuple(sorted(name for name in names if forbidden(name)))


def command_env(requested: Mapping[str, str], *, account: Account) -> dict[str, str]:
    """Exactly ``requested``, plus ``HOME``, ``USER`` and ``LOGNAME`` when it lacks them."""
    identity = {"HOME": str(account.home), "USER": account.name, "LOGNAME": account.name}
    return identity | dict(requested)


def is_inside(path: Path, root: Path) -> bool:
    """Whether ``path`` lies strictly below ``root`` once both are resolved."""
    resolved = path.resolve()
    base = root.resolve()
    return resolved != base and resolved.is_relative_to(base)


def _invalid(message: str) -> SpawnFailed:
    return SpawnFailed(code=SpawnErrorCode.INVALID_REQUEST, message=message)


def plan_run(
    request: SpawnRequest, account: Account, *, data_root: Path, output_limit_bytes: int
) -> LaunchPlan | SpawnFailed:
    """Check ``request`` against the policy and build what the launcher starts."""
    if not is_inside(request.cwd, data_root):
        return _invalid(f"working directory {request.cwd} is not inside {data_root}")
    if names := forbidden_env(request.env, request.user):
        return _invalid(f"not allowed for {request.user}: {', '.join(names)}")
    return LaunchPlan(
        argv=request.argv,
        cwd=request.cwd,
        env=command_env(request.env, account=account),
        account=account,
        timeout=None if request.timeout_s is None else timedelta(seconds=request.timeout_s),
        stdin=request.stdin,
        output_limit_bytes=output_limit_bytes,
    )


def _bits(mask: int) -> frozenset[int]:
    return frozenset(bit for bit in range(mask.bit_length()) if mask >> bit & 1)


def check_capabilities(sets: CapabilitySets) -> CapabilityCheck:
    """Exactly the required capabilities, and none others even in the bounding set."""
    missing = REQUIRED_CAPABILITIES - _bits(sets.effective)
    extra = (_bits(sets.effective) | _bits(sets.bounding)) - REQUIRED_CAPABILITIES
    if missing or extra:
        return CapabilitiesWrong(missing=missing, extra=extra)
    return CapabilitiesOk()
