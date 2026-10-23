from datetime import timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from git_manager.config.types import Duration, format_duration

DURATION: TypeAdapter[timedelta] = TypeAdapter(Duration)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("60s", timedelta(seconds=60)),
        ("10m", timedelta(minutes=10)),
        ("2h", timedelta(hours=2)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("1h 30m", timedelta(hours=1, minutes=30)),
        ("250ms", timedelta(milliseconds=250)),
        ("1d", timedelta(days=1)),
        (90, timedelta(seconds=90)),
        (timedelta(minutes=3), timedelta(minutes=3)),
    ],
)
def test_durations_read_like_the_spec_example(text: object, expected: timedelta) -> None:
    assert DURATION.validate_python(text) == expected


@pytest.mark.parametrize("bad", ["", "10", "ten minutes", "10x", "1hx2m", "-5s"])
def test_invalid_durations_explain_the_format(bad: str) -> None:
    with pytest.raises(ValidationError, match="like 90s or 1h30m"):
        DURATION.validate_python(bad)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (timedelta(0), "0s"),
        (timedelta(seconds=60), "1m"),
        (timedelta(hours=1, minutes=30), "1h30m"),
        (timedelta(seconds=1, milliseconds=500), "1s500ms"),
    ],
)
def test_durations_are_written_back_in_config_style(value: timedelta, text: str) -> None:
    assert format_duration(value) == text
    assert DURATION.dump_python(value, mode="json") == text
    assert DURATION.validate_python(text) == value
