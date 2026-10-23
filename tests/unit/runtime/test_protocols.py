from datetime import timedelta
from pathlib import Path

from git_manager.runtime import (
    Clock,
    Command,
    IdGenerator,
    ProcessCompleted,
    ProcessResult,
    ProcessRunner,
    ProcessTimedOut,
)
from tests.conftest import START, FakeProcessRunner, FixedClock, SequentialIds


async def test_fake_runner_records_commands_and_answers_with_its_responder() -> None:
    def time_out(_command: Command) -> ProcessResult:
        return ProcessTimedOut(stdout="", stderr="", duration=timedelta(minutes=30))

    fake = FakeProcessRunner(respond=time_out)
    runner: ProcessRunner = fake
    command = Command(argv=("just", "test"), cwd=Path(), timeout=timedelta(minutes=30))

    result = await runner.run(command)

    assert isinstance(result, ProcessTimedOut)
    assert fake.commands == [command]


async def test_fake_runner_exits_zero_by_default(process_runner: FakeProcessRunner) -> None:
    result = await process_runner.run(Command(argv=("true",), cwd=Path()))

    assert isinstance(result, ProcessCompleted)
    assert result.succeeded


def test_fixed_clock_moves_only_when_advanced() -> None:
    fake = FixedClock()
    clock: Clock = fake

    fake.advance(timedelta(minutes=10))

    assert clock.now() == START + timedelta(minutes=10)
    assert clock.now().tzinfo is not None


def test_sequential_ids_never_repeat() -> None:
    ids: IdGenerator = SequentialIds(prefix="run")

    assert [ids.new_id() for _ in range(3)] == ["run-1", "run-2", "run-3"]
