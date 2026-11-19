"""The server settings a client may change, with validation and persistence."""

from dataclasses import asdict, dataclass, replace

from decker.common import config

_MIB = 1024 * 1024
MIN_MEMORY_LIMIT = 128 * _MIB
MAX_MEMORY_LIMIT = 1024 * 1024 * _MIB
MIN_IMAGE_FILE_SIZE = 64 * 1024
MAX_IMAGE_FILE_SIZE = 64 * _MIB


class SettingsError(ValueError):
    """Raised when a requested settings change is invalid."""


@dataclass(frozen=True)
class ServerSettings:
    """Settings editable from the client's Server tab (the host is a client-side setting only)."""

    port: int
    memory_limit: int
    icon_max_file_size: int
    stop_when_last_client_leaves: bool

    def to_dict(self) -> dict[str, object]:
        """Return the settings as a plain dict."""
        return asdict(self)


def read_settings() -> ServerSettings:
    """Return the current settings from config."""
    return ServerSettings(
        port=config.get_as("server.port", int),
        memory_limit=config.get_as("server.memory_limit", int),
        icon_max_file_size=config.get_as_or_default("icons.max_file_size", int, 4 * _MIB),
        stop_when_last_client_leaves=config.get_as_or_default("server.stop_when_last_client_leaves", bool, False),
    )


def _int_in_range(name: str, value: object, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsError(f"{name} must be an integer")
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


def validate(values: dict[str, object]) -> ServerSettings:
    """Merge `values` over the current settings, raising SettingsError for unknown keys or bad values."""
    current = read_settings()
    unknown = sorted(set(values) - set(current.to_dict()))
    if unknown:
        raise SettingsError(f"unknown setting: {', '.join(unknown)}")
    changes: dict[str, object] = {}
    if "port" in values:
        changes["port"] = _int_in_range("port", values["port"], 1, 65535)
    if "memory_limit" in values:
        changes["memory_limit"] = _int_in_range("memory_limit", values["memory_limit"], MIN_MEMORY_LIMIT, MAX_MEMORY_LIMIT)
    if "icon_max_file_size" in values:
        changes["icon_max_file_size"] = _int_in_range(
            "icon_max_file_size", values["icon_max_file_size"], MIN_IMAGE_FILE_SIZE, MAX_IMAGE_FILE_SIZE
        )
    if "stop_when_last_client_leaves" in values:
        flag = values["stop_when_last_client_leaves"]
        if not isinstance(flag, bool):
            raise SettingsError("stop_when_last_client_leaves must be true or false")
        changes["stop_when_last_client_leaves"] = flag
    return replace(current, **changes)  # type: ignore[arg-type]


def write_settings(new: ServerSettings) -> bool:
    """Persist `new` and return True when a server restart is needed to apply it."""
    old = read_settings()
    config.set("server.port", new.port)
    config.set("server.memory_limit", new.memory_limit)
    config.set("icons.max_file_size", new.icon_max_file_size)
    config.set("server.stop_when_last_client_leaves", new.stop_when_last_client_leaves)
    return (new.port, new.memory_limit, new.icon_max_file_size) != (old.port, old.memory_limit, old.icon_max_file_size)
