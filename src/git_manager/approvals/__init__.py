"""Approvals: who decided, the gate a run stops at, and the API scopes that allow it."""

from git_manager.approvals.models import (
    Actor,
    ActorType,
    ApiToken,
    Principal,
    Scope,
    TokensFile,
)
from git_manager.approvals.protocols import ApprovalGate, Authenticator
from git_manager.approvals.tokens import (
    SOCKET_PRINCIPAL,
    TokenAuthenticator,
    TokensFileError,
    TrustedAuthenticator,
    load_tokens,
)

__all__ = [
    "SOCKET_PRINCIPAL",
    "Actor",
    "ActorType",
    "ApiToken",
    "ApprovalGate",
    "Authenticator",
    "Principal",
    "Scope",
    "TokenAuthenticator",
    "TokensFile",
    "TokensFileError",
    "TrustedAuthenticator",
    "load_tokens",
]
