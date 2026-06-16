"""Process-wide, read-mostly state shared across client views."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from decker.client.connection_manager import ConnectionManager
    from decker.client.window import MainWindow


@dataclass
class AppContext:
    """Shared client state. MainWindow is the sole writer; views are read-only consumers."""

    connected: bool = False
    active_device: str | None = None
    last_command: str | None = None
    window: "MainWindow | None" = None
    connection_manager: "ConnectionManager | None" = field(default=None, repr=False)

    _instance: ClassVar["AppContext | None"] = None

    @classmethod
    def get(cls) -> "AppContext":
        """Return the process-wide AppContext instance, creating it on first use."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Replace the singleton with a fresh instance — used by MainWindow.restart()."""
        cls._instance = cls()
