"""Configuration storage backends."""

from pathlib import Path
from typing import Any

import yaml


class ReadOnlyBackend:
    """Base class for read-only configuration backends."""

    def load(self) -> dict[str, Any]:
        """Load and return raw (nested) configuration data."""
        raise NotImplementedError


class WritableBackend(ReadOnlyBackend):
    """Base class for read-write configuration backends."""

    def save(self, data: dict[str, Any]) -> None:
        """Persist raw (nested) configuration data."""
        raise NotImplementedError


class DefaultBackend(ReadOnlyBackend):
    """Loads bundled application defaults from a YAML file."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def load(self) -> dict[str, Any]:
        """Load and return the YAML file contents. Raises FileNotFoundError if missing."""
        with open(self._path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}


class UserBackend(WritableBackend):
    """Loads and saves user configuration as a YAML file, creating it on first save."""

    def __init__(self, path: str | Path):
        self._path = Path(path)

    def load(self) -> dict[str, Any]:
        """Load and return the YAML file contents, or an empty dict if the file does not exist."""
        if not self._path.exists():
            return {}
        with open(self._path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def save(self, data: dict[str, Any]) -> None:
        """Persist data to the YAML file, creating parent directories as needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)


class MemoryBackend(WritableBackend):
    """In-memory runtime overrides; never persisted to disk."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """Return the current in-memory data."""
        return self._data

    def save(self, data: dict[str, Any]) -> None:
        """Replace the in-memory data entirely."""
        self._data = data
