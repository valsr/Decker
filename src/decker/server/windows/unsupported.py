"""Fallback backend for sessions without focus detection."""

from typing import Callable

from decker.common.model import WindowInfo
from decker.server.windows.backend import BackendStatus


class UnsupportedBackend:
    """Placeholder backend that never reports windows and explains why."""

    supports_pick = False

    def __init__(self, reason: str, name: str = "unsupported", state: str = "unsupported") -> None:
        self.name = name
        self._status = BackendStatus(state, reason)

    def available(self) -> BackendStatus:
        """Report the fixed status given at construction."""
        return self._status

    def start(self, on_change: Callable[[WindowInfo], None]) -> None:  # pylint: disable=unused-argument
        """Do nothing."""
        return None

    def stop(self) -> None:
        """Do nothing."""
        return None

    def pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        """Report no window."""
        on_result(None)
