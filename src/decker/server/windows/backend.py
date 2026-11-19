"""Window backend interface."""

from dataclasses import dataclass
from typing import Callable, Protocol

from decker.common.model import WindowInfo


@dataclass(frozen=True)
class BackendStatus:
    """Whether a backend can run; state is "active", "unavailable" or "unsupported"."""

    state: str
    reason: str = ""


class WindowBackend(Protocol):
    """Source of focused-window changes for one desktop environment."""

    name: str
    supports_pick: bool

    def available(self) -> BackendStatus:
        """Report whether the backend can run here."""
        ...

    def start(
        self, on_change: Callable[[WindowInfo], None], on_failure: Callable[[Exception], None] | None = None
    ) -> None:
        """Begin reporting; call on_failure(exc) once, from the backend's thread, if the source dies after start."""
        ...

    def stop(self) -> None:
        """Stop reporting."""
        ...

    def pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        """Let the user click a window; report it or None."""
        ...
