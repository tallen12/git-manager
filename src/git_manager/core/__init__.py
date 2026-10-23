"""Service core: the operations every interface exposes, defined once."""

from git_manager.core.protocols import Operations
from git_manager.core.service import Service

__all__ = ["Operations", "Service"]
