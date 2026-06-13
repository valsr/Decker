"""Multilayer application configuration.

Precedence (lowest → highest): defaults (bundled YAML) < user (~/.decker/config.yaml) < memory (runtime overrides).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args, get_origin

import flatten_dict

from decker.common.config.backend import (
    DefaultBackend,
    MemoryBackend,
    ReadOnlyBackend,
    UserBackend,
    WritableBackend,
)

# ---------------------------------------------------------------------------
# Public type alias
# ---------------------------------------------------------------------------

ValueType = str | int | float | bool | list[Any] | None

# ---------------------------------------------------------------------------
# Module-level paths
# ---------------------------------------------------------------------------

_DEFAULTS_PATH: Path = Path(__file__).parent / "defaults.yml"
_USER_CONFIG_PATH: Path = Path.home() / ".decker" / "config.yaml"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TRUTHY: frozenset[str] = frozenset(("true", "yes", "1", "y", "on"))
_FALSY: frozenset[str] = frozenset(("false", "no", "0", "n", "off"))


def _flatten(data: dict[str, Any]) -> dict[str, ValueType]:
    if not data:
        return {}
    return flatten_dict.flatten(data, reducer="dot")


def _unflatten(data: dict[str, ValueType]) -> dict[str, Any]:
    if not data:
        return {}
    return flatten_dict.unflatten(data, splitter="dot")


def _is_valid(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, list, type(None)))


def _to_bool(value: ValueType) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lower = value.lower().strip()
        if lower in _TRUTHY:
            return True
        if lower in _FALSY:
            return False
        raise ValueError(f"Cannot interpret {value!r} as bool")
    raise TypeError(f"Cannot convert {type(value).__name__} to bool")


def _to_list(value: ValueType) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [item.strip() for item in value.split(",")]
    return [value]


def _convert(value: ValueType, target: type) -> Any:
    """Convert value to target type, supporting generic aliases like list[int]."""
    origin = get_origin(target)

    if origin is list or target is list:
        lst = _to_list(value)
        args = get_args(target)
        if args:
            return [_convert(item, args[0]) for item in lst]
        return lst

    if target is bool:
        return _to_bool(value)

    if isinstance(value, target):
        return value

    try:
        return target(value)
    except (ValueError, TypeError) as exc:
        name = getattr(target, "__name__", str(target))
        raise TypeError(f"Cannot convert {value!r} to {name}") from exc


# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------


class Config:
    """Multilayer configuration manager: defaults < user < memory."""

    def __init__(
        self,
        defaults_backend: ReadOnlyBackend,
        user_backend: WritableBackend,
        memory_backend: MemoryBackend,
    ):
        self._defaults_backend = defaults_backend
        self._user_backend = user_backend
        self._memory_backend = memory_backend
        self._defaults: dict[str, ValueType] = {}
        self._user: dict[str, ValueType] = {}
        self._memory: dict[str, ValueType] = {}

    def load(self) -> None:
        """Load defaults and user layers from their backends."""
        self._defaults = _flatten(self._defaults_backend.load())
        self._user = _flatten(self._user_backend.load())

    def load_memory(self, data: dict[str, Any]) -> None:
        """Replace the memory layer with runtime overrides (e.g. parsed CLI args)."""
        self._memory_backend.save(data)
        self._memory = _flatten(self._memory_backend.load())

    def has(self, path: str) -> bool:
        """Return True if path exists in any layer."""
        return path in self._memory or path in self._user or path in self._defaults

    def get(self, path: str) -> ValueType:
        """Return the value for path (memory > user > defaults). Raises KeyError if absent."""
        if path in self._memory:
            return self._memory[path]
        if path in self._user:
            return self._user[path]
        if path in self._defaults:
            return self._defaults[path]
        raise KeyError(path)

    def get_or_default(self, path: str, default: Any) -> Any:
        """Return the value for path, or default if the path is not found."""
        try:
            return self.get(path)
        except KeyError:
            return default

    def get_as(self, path: str, target_type: type) -> Any:
        """Return the value for path converted to target_type. Raises KeyError if absent."""
        return _convert(self.get(path), target_type)

    def get_as_or_default(self, path: str, target_type: type, default: Any) -> Any:
        """Return the converted value, or default if not found or conversion fails."""
        try:
            return self.get_as(path, target_type)
        except (KeyError, TypeError, ValueError):
            return default

    def get_all(self, path: str | None = None) -> dict[str, ValueType]:
        """Return a flat dict of all values merged across layers.

        If path is given, only keys equal to or prefixed by ``path.`` are returned.
        """
        merged: dict[str, ValueType] = {**self._defaults, **self._user, **self._memory}
        if path is None:
            return merged
        prefix = path + "."
        return {k: v for k, v in merged.items() if k == path or k.startswith(prefix)}

    def set(self, path: str, value: ValueType) -> None:
        """Write value to the user layer and persist immediately.

        Raises TypeError for unsupported value types.
        """
        if not _is_valid(value):
            raise TypeError(f"Invalid configuration value type: {type(value).__name__}")
        self._user[path] = value
        self._user_backend.save(_unflatten(self._user))

    def unset(self, path: str) -> None:
        """Remove path (and any sub-keys) from the user layer and persist.

        No-op if path is not in the user layer.
        """
        prefix = path + "."
        keys = [k for k in self._user if k == path or k.startswith(prefix)]
        if not keys:
            return
        for k in keys:
            del self._user[k]
        self._user_backend.save(_unflatten(self._user))


# ---------------------------------------------------------------------------
# Module-level singleton and API
# ---------------------------------------------------------------------------

_config: Config = Config(DefaultBackend(_DEFAULTS_PATH), UserBackend(_USER_CONFIG_PATH), MemoryBackend())
_config.load()


def has(path: str) -> bool:
    """Return True if path exists in any configuration layer."""
    return _config.has(path)


def get(path: str) -> ValueType:
    """Return the value for path. Raises KeyError if not found in any layer."""
    return _config.get(path)


def get_or_default(path: str, default: Any) -> Any:
    """Return the value for path, or default if the path is not found."""
    return _config.get_or_default(path, default)


def get_as(path: str, target_type: type) -> Any:
    """Return the value for path converted to target_type. Raises KeyError if not found."""
    return _config.get_as(path, target_type)


def get_as_or_default(path: str, target_type: type, default: Any) -> Any:
    """Return the converted value, or default if not found or conversion fails."""
    return _config.get_as_or_default(path, target_type, default)


def get_all(path: str | None = None) -> dict[str, ValueType]:
    """Return a flat dict of all values, optionally filtered by path prefix."""
    return _config.get_all(path)


def set(path: str, value: ValueType) -> None:  # pylint: disable=redefined-builtin
    """Write value to the user layer and persist to disk."""
    _config.set(path, value)


def unset(path: str) -> None:
    """Remove path from the user layer and persist to disk."""
    _config.unset(path)


def load_memory(data: dict[str, Any]) -> None:
    """Populate the memory (highest-priority) layer with runtime overrides."""
    _config.load_memory(data)
