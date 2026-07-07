"""Process-wide, read-mostly state shared across client views."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from decker.common.model import DeviceHardwareInfo

if TYPE_CHECKING:
    from decker.client.connection_manager import ConnectionManager
    from decker.client.window import MainWindow


@dataclass
class AppContext:
    """Shared client state. MainWindow is the sole writer; views are read-only consumers."""

    """The prefix/global path used to locate configuration/files"""
    path_prefix: str = "~/"

    connected: bool = False
    active_device: DeviceHardwareInfo | None = None
    last_command: str | None = None
    window: "MainWindow | None" = None
    connection_manager: "ConnectionManager | None" = field(default=None, repr=False)

    _instance: ClassVar["AppContext | None"] = None

    @property
    def active_device_id(self) -> str | None:
        """Convenience accessor returning only the device ID of the active device."""
        return self.active_device.id if self.active_device is not None else None

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

    # TODO Configuration is part of APPContext
