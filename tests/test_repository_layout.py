from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_claude_skills_link_to_shared_agent_skills() -> None:
    # A clone with core.symlinks=false checks this out as a plain file, which hides every
    # shared skill from Claude Code.
    link = ROOT / ".claude" / "skills"

    assert link.is_symlink()
    assert link.resolve() == (ROOT / ".agents" / "skills").resolve()
