"""Environment scrubbing: commands start from nothing plus a short allowlist."""

from collections.abc import Mapping

INHERITED_VARIABLES = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR"})
"""Variables a locally run command inherits from the orchestrator. None holds a secret."""

SUPERVISED_INHERITED_VARIABLES = INHERITED_VARIABLES - {"HOME"}
"""The same for supervised commands; the supervisor sets ``HOME`` for the target user."""


def scrubbed_environment(
    command_env: Mapping[str, str],
    *,
    inherited: Mapping[str, str],
    allowed: frozenset[str] = INHERITED_VARIABLES,
) -> dict[str, str]:
    """Return the allowlisted part of ``inherited`` overlaid with the command's own env.

    Anything else in ``inherited`` (tokens, ``GM_*`` settings, ``SSH_AUTH_SOCK``) is
    dropped, so a credential reaches a command only when the caller put it in ``env``.
    """
    base = {name: value for name, value in inherited.items() if name in allowed}
    return base | dict(command_env)
