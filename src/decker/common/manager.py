"""Abstract base class for server-side managers with explicit two-phase lifecycle."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext


class Manager(ABC):
    """Base for all server managers. Separate construction from resource acquisition."""

    @abstractmethod
    def create(self, context: ServerContext) -> None:
        """Acquire resources. Called once after construction, before any other method."""

    @abstractmethod
    def destroy(self) -> None:
        """Release resources. Called once during shutdown."""
