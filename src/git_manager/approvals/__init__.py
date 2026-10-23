"""Approvals: who decided, and the gate a run stops at when a human must approve."""

from git_manager.approvals.models import Actor, ActorType
from git_manager.approvals.protocols import ApprovalGate

__all__ = ["Actor", "ActorType", "ApprovalGate"]
