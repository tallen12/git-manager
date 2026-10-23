"""Approval value types for M1; the approval record itself arrives with M3."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ActorType(StrEnum):
    """How a decision reached Git Manager; recorded in the audit log."""

    HUMAN_CLI = "human-cli"
    HUMAN_REST = "human-rest"
    MCP_AGENT = "mcp-agent"


class Actor(BaseModel):
    """Who made a decision or confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ActorType
    identity: str = Field(min_length=1, description="User name or token name.")
