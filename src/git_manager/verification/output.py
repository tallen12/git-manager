"""Shaping command output into run artifacts."""

OUTPUT_TAIL_LINES = 500
"""How many lines of output a ``TestResult`` keeps."""


def tail_lines(text: str, limit: int = OUTPUT_TAIL_LINES) -> str:
    """Return the last ``limit`` lines of ``text``, keeping its final newline."""
    lines = text.splitlines(keepends=True)
    return "".join(lines[-limit:])


def combined_output(stdout: str, stderr: str) -> str:
    """Stdout followed by stderr.

    The runner captures the streams separately, so their interleaving is lost; stderr goes
    last because that is where crashes usually end up, and the tail keeps the end.
    """
    if stdout and stderr and not stdout.endswith("\n"):
        return f"{stdout}\n{stderr}"
    return stdout + stderr
