"""Enter a command's working directory as its user, then execute the command.

``subprocess`` changes directory before it switches user, and the supervisor (root without
``CAP_DAC_READ_SEARCH``) cannot enter a ``0700`` worktree that belongs to ``gm-claude`` or
``gm-tests``. The launcher therefore starts this module as the target user, and it changes
directory and executes the command itself.

Usage: ``python -I -m git_manager.supervisor.enter STATUS_FD CWD UNSET PROGRAM [ARG...]``.
``UNSET`` is a comma-separated list of variables to remove before executing: Python adds
``LC_CTYPE`` to its own environment when the locale is ``C`` (PEP 538), and the command
must get exactly the environment it was given. When
the directory or the program fails, it writes ``<errno>\\n<message>`` to ``STATUS_FD`` and
exits 127; on success the descriptor closes on exec, so the launcher reads end of file.

This module must stay importable with nothing but the standard library: it runs for every
command, so keep it small.
"""

import os
import sys
from collections.abc import Sequence

SPAWN_FAILED_EXIT = 127
# STATUS_FD, CWD, UNSET and PROGRAM.
_MIN_ARGS = 4


def encode_failure(error: OSError) -> bytes:
    """The status-pipe message for ``error``."""
    return f"{error.errno or 0}\n{error}".encode()


def main(argv: Sequence[str] | None = None) -> None:
    """Change directory and execute; only returns by raising ``SystemExit``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < _MIN_ARGS:
        msg = "usage: enter STATUS_FD CWD UNSET PROGRAM [ARG...]"
        raise SystemExit(msg)
    status_fd, cwd, unset, program = int(args[0]), args[1], args[2], args[3:]
    os.set_inheritable(status_fd, False)
    for name in filter(None, unset.split(",")):
        os.environ.pop(name, None)
    try:
        os.chdir(cwd)
        os.execvp(program[0], program)
    except OSError as error:
        os.write(status_fd, encode_failure(error))
        raise SystemExit(SPAWN_FAILED_EXIT) from error


if __name__ == "__main__":
    main()
