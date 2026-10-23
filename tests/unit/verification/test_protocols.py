from pathlib import Path

from git_manager.config import VerifyConfig
from git_manager.verification import (
    CommandSource,
    Verifier,
    VerifyCommands,
    VerifyFailed,
    VerifyPassed,
    VerifyStep,
)
from tests.conftest import FakeVerifier

COMMANDS = VerifyCommands(test="just test", source=CommandSource.CONFIG, source_hash="h")


async def test_fake_verifier_passes_by_default_and_records_calls() -> None:
    fake = FakeVerifier()
    verifier: Verifier = fake

    outcome = await verifier.verify(
        worktree=Path("w"), commands=COMMANDS, config=VerifyConfig(), run_id="run-1"
    )

    assert isinstance(outcome, VerifyPassed)
    assert [call.run_id for call in fake.calls] == ["run-1"]


async def test_fake_verifier_replays_scripted_outcomes() -> None:
    failed = VerifyFailed(results=(), failed_step=VerifyStep.TEST)
    verifier: Verifier = FakeVerifier(outcomes=[failed])

    outcome = await verifier.verify(
        worktree=Path("w"), commands=COMMANDS, config=VerifyConfig(), run_id="run-1"
    )

    assert outcome == failed
