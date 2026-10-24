import pytest
from pydantic import ValidationError

from git_manager.approvals import Actor, ActorType


def test_actor_serializes_with_the_audit_log_names() -> None:
    actor = Actor(type=ActorType.MCP_AGENT, identity="review-bot")

    assert actor.model_dump(mode="json") == {"type": "mcp-agent", "identity": "review-bot"}


def test_actor_needs_an_identity() -> None:
    with pytest.raises(ValidationError):
        Actor(type=ActorType.HUMAN_CLI, identity="")
