from datetime import UTC, datetime

from git_manager.runtime import Clock, IdGenerator
from git_manager.runtime.system import RandomIds, SystemClock


def test_clock_reads_aware_utc_time() -> None:
    clock: Clock = SystemClock()
    before = datetime.now(UTC)

    now = clock.now()

    assert now.tzinfo is UTC
    assert before <= now <= datetime.now(UTC)


def test_ids_are_short_hex_and_distinct() -> None:
    ids: IdGenerator = RandomIds()

    issued = {ids.new_id() for _ in range(1000)}

    assert len(issued) == 1000
    assert all(len(value) == 16 and int(value, 16) >= 0 for value in issued)
