"""Field types for the hand-written YAML config."""

import re
from datetime import timedelta
from typing import Annotated

from pydantic import BeforeValidator, ByteSize, PlainSerializer

_DURATION = re.compile(r"(?P<amount>\d+)(?P<unit>ms|s|m|h|d)")
_UNITS = {
    "ms": timedelta(milliseconds=1),
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
}


def parse_duration(value: object) -> object:
    """Read ``90s``, ``10m``, ``2h`` or a combination like ``1h30m``; pass others through.

    A bare number means seconds. ``timedelta`` values pass through unchanged, so models
    built in code need no strings.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return timedelta(seconds=value)
    if not isinstance(value, str):
        return value
    text = value.replace(" ", "")
    matches = list(_DURATION.finditer(text))
    if not text or "".join(match[0] for match in matches) != text:
        msg = f"invalid duration {value!r}: use a number with ms, s, m, h or d, like 90s or 1h30m"
        raise ValueError(msg)
    return sum((int(match["amount"]) * _UNITS[match["unit"]] for match in matches), timedelta())


def format_duration(value: timedelta) -> str:
    """Write a duration back in the config's own style (``90s``, ``10m``, ``1h30m``)."""
    milliseconds = round(value.total_seconds() * 1000)
    if milliseconds == 0:
        return "0s"
    parts: list[str] = []
    for unit, size in (("d", 86_400_000), ("h", 3_600_000), ("m", 60_000), ("s", 1000)):
        amount, milliseconds = divmod(milliseconds, size)
        if amount:
            parts.append(f"{amount}{unit}")
    if milliseconds:
        parts.append(f"{milliseconds}ms")
    return "".join(parts)


Duration = Annotated[
    timedelta,
    BeforeValidator(parse_duration),
    PlainSerializer(format_duration, return_type=str, when_used="json"),
]
# ``4G`` and ``200M`` as in the spec; pydantic reads decimal and binary units.
Size = ByteSize
