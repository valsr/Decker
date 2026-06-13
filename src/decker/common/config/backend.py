"""Configuration backends for loading and saving settings."""

import os
from copy import deepcopy
from typing import Any

import toml


class ReadOnlyConfigBackend:
    """
    Base class for readonly configuration backends.

    This class defines the interface for loading configuration data.
    Subclasses should implement the `load` methods.
    """

    def load(self) -> dict[str, Any]:
        """Load configuration data."""
        raise NotImplementedError("Subclasses must implement this method.")


class ConfigBackend(ReadOnlyConfigBackend):
    """
    Base class for configuration backends.

    This class defines the interface for loading and saving configuration data.
    Subclasses should implement the `load` and `save` methods.
    """

    def save(self, settings: dict[str, Any]) -> None:
        """Save configuration settings."""
        raise NotImplementedError("Subclasses must implement this method.")


class MemoryBackend(ConfigBackend):
    """
    MemoryBackend provides functionality to load and save configuration data
    in memory.

    Notes:
        This class does not persist configuration data to a file and is intended
        for use cases where configuration is managed entirely in memory.
    """

    def __init__(self, data: dict[str, Any] | None = None):
        """Initialize a new instance of the configuration."""
        self._config = data if data is not None else {}

    def load(self) -> dict[str, Any]:
        """
        Load configuration data from memory.

        Returns:
            dict[str, Any]: The current in-memory configuration data.
        """
        return deepcopy(self._config)

    def save(self, settings: dict[str, Any]) -> None:
        """
        Saves configuration settings to memory.

        Parameters:
            settings (dict[str, Any]): A dictionary containing the configuration settings.
        """
        self._config = settings


class ReadOnlyMemoryBackend(ReadOnlyConfigBackend):
    """
    ReadOnlyMemoryBackend provides functionality to load configuration data
    from memory.

    Notes:
        This class does not persist configuration data to a file and is intended
        for use cases where configuration is managed entirely in memory.
    """

    def __init__(self, data: dict[str, Any] | None = None):
        """Initialize a new instance of the configuration."""
        self._config = data if data is not None else {}

    def load(self) -> dict[str, Any]:
        """
        Load configuration data from memory.

        Returns:
            dict[str, Any]: The current in-memory configuration data.
        """
        return deepcopy(self._config)


class TomlFileBackend(ConfigBackend):
    """
    TomlFileBackend provides functionality to load and save configuration data
    from a TOML formatted file.

    Notes:
        This class depends on an external constant (e.g., CONFIG_KEY) and the toml
        module for serialization and deserialization of configuration data.
    """

    def __init__(self, path: str):
        """
        Initialize a new instance of the configuration.

        Parameters:
            path (str): The file path for storing or accessing configuration data.
        """
        self._path = path

    def load(self) -> dict[str, Any]:
        """
        Load configuration data from a TOML file.

        Returns:
            dict[str, Any]: Parsed configuration data from toml file.

        Raises:
            FileNotFoundError: If the configuration file is not found at self._path.
            PermissionError: If the configuration file cannot be read.
        """
        if not os.path.exists(self._path):
            raise FileNotFoundError(f"Config file not found: {self._path}")
        if not os.access(self._path, os.R_OK):
            raise PermissionError(f"Cannot read config file: {self._path}")

        return toml.load(self._path)

    def save(self, settings: dict[str, Any]) -> None:
        """
        Saves configuration settings to a file in TOML format.

        Parameters:
            settings (dict[str, Any]): A dictionary containing the configuration settings.

        Raises:
            PermissionError: If the configuration file exists but cannot be read.
        """
        if os.path.exists(self._path):
            if not os.access(self._path, os.R_OK):
                raise PermissionError(f"Cannot read config file: {self._path}")

        with open(self._path, "w", encoding="UTF-8") as file:
            toml.dump(settings, file)
