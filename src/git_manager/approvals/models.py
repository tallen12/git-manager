"""Approval value types: who decided, and the API scopes and tokens that allow it.

The approval record itself arrives with M3.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


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


class Scope(StrEnum):
    """What an API caller may do. A token lists every scope it has; none implies another.

    ``read`` sees state; ``operate`` syncs, pauses, resumes, tracks and changes
    non-sensitive config; ``approve`` approves, retargets, confirms test commands, resets
    the budget and changes sensitive config. MCP tokens never get ``approve``.
    """

    READ = "read"
    OPERATE = "operate"
    APPROVE = "approve"


class Principal(BaseModel):
    """Who an API request acts as: a token's name and scopes, or the Unix socket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    scopes: frozenset[Scope]

    def allows(self, scope: Scope) -> bool:
        """Whether this principal holds ``scope``."""
        return scope in self.scopes


# Shorter tokens are guessable; 32 characters is what ``openssl rand -hex 16`` prints.
MIN_TOKEN_LENGTH = 32


class ApiToken(BaseModel):
    """One entry of the tokens file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="Shown in the audit log and in 403 errors.")
    token: SecretStr = Field(min_length=MIN_TOKEN_LENGTH)
    scopes: frozenset[Scope] = Field(min_length=1)


class TokensFile(BaseModel):
    """The API tokens file (``http.tokens_file``): every token the daemon accepts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tokens: tuple[ApiToken, ...]

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        names = [entry.name for entry in self.tokens]
        if duplicates := sorted({name for name in names if names.count(name) > 1}):
            msg = f"token names must be unique: {', '.join(duplicates)}"
            raise ValueError(msg)
        values = [entry.token.get_secret_value() for entry in self.tokens]
        if len(set(values)) != len(values):
            # Never quote the value: it is a secret.
            msg = "two entries share a token value; give each its own"
            raise ValueError(msg)
        return self
