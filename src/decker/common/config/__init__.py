"""Module for managing application configurations."""

import builtins
import datetime
import logging
import os
from collections.abc import Callable, Generator
from typing import Any

import flatten_dict
from _collections_abc import dict_items, dict_keys, dict_values

from decker.common.config.backend import (
    ConfigBackend,
    ReadOnlyConfigBackend,
    TomlFileBackend,
)

ValueType = (
    str
    | int
    | float
    | complex
    | list[Any]
    | set[Any]  # pylint: disable=used-before-assignment
    | frozenset[Any]
    | bool
    | bytes
    | bytearray
    | datetime.datetime
)

config_items = dict_items[str, ValueType]
config_keys = dict_keys[str, ValueType]
config_values = dict_values[str, ValueType]

KEY_SEPARATOR = "."
USER_CONFIG_FILE = "~/.decker"


def is_valid_value_type(value: Any) -> bool:
    """
    Check if the value is of a valid type for configuration.

    Args:
        value (Any): The value to check.

    Returns:
        bool: True if the value is of a valid type, otherwise False.
    """
    return isinstance(
        value, (str, int, float, complex, list, builtins.set, frozenset, bool, bytes, bytearray, datetime.datetime)
    )


def _match_key_exactly(key: str, value: ValueType) -> bool:
    return key == key


def _match_key_or_subkey(key: str, value: ValueType) -> bool:
    return key == key or key.startswith(key + KEY_SEPARATOR)


class ReadOnlyConfigSource:
    """
    A class for managing configuration data from a single backend.
    """

    def __init__(self, name: str, backend: ReadOnlyConfigBackend):
        """
        Initialize the configuration instance with the given backend manager.

        Args:
            name (str): The name of the configuration source.
            backend (decker.common.config.backend.ConfigBackend): An instance managing backend operations.
        """
        self._name = name
        self._backend = backend
        self._data: dict[str, ValueType] = {}  # flat dictionary

    @property
    def name(self) -> str:
        """Get the name of the configuration source."""
        return self._name

    def get_backend(self) -> ReadOnlyConfigBackend:
        """
        Get the backend associated with this configuration source.

        Returns:
            ReadOnlyConfigBackend: The backend managing the configuration data.
        """
        return self._backend

    def load(self):
        """Load configuration data from the backend."""
        data = self._backend.load()
        self._data = flatten_dict.flatten(data, reducer="dot")

    def has(self, key: str) -> bool:
        """Check if the given key exists within the internal configuration data.

        Args:
            key (str): The key to search for in the configuration data.

        Returns:
            bool: True if the key is found in the configuration data, otherwise False.
        """
        return key in self._data

    def get(self, key: str) -> ValueType:
        """
        Retrieve the configuration value for the given key.

        Parameters:
            key (str): The key for which to retrieve the configuration value.

        Returns:
            ValueType: The value associated with the key if it exists.

        Raises:
            KeyError: If the key is not found in the collection.
        """
        return self.__getitem__(key)

    def items(self, key: str | None = None) -> config_items:
        """
        Retrieve configuration entries that match the provided key or its sub-keys.

        Parameters:
            key (str, Optional): The configuration key to filter by. If None, all entries are returned.

        Returns:
            list[tuple[str, ValueType]]: A list of tuples, where each tuple contains a key and its value.
        """
        if not key:
            return self._data.items()
        return dict(self.find(_match_key_or_subkey)).items()

    def keys(self) -> config_keys:
        """Retrieve all keys in the configuration data."""
        return self._data.keys()

    def values(self) -> config_values:
        """Retrieve all values in the configuration data."""
        return self._data.values()

    def __getitem__(self, key: str) -> ValueType:
        """
        Retrieve the value associated with the given key.

        Parameters:
            key (str): The key whose corresponding value is to be returned.

        Returns:
            ValueType: The value associated with the provided key.

        Raises:
            KeyError: If the key is not found in the collection.
        """
        return self._data[key]

    def find(self, callback: Callable[[str, ValueType], bool]) -> Generator[tuple[str, ValueType], None, None]:
        """
        Iterates over the internal data dictionary and yields key-value pairs for which the provided callback
        returns True.

        Parameters:
            callback (Callable[[str, ValueType], bool]): A function that takes a key and a value from the
                internal data dictionary and returns a boolean. If it returns True, the key-value pair is
                yielded.

        Yields:
            tuple[str, ValueType]: A tuple containing key-value pairs from the internal data dictionary
                for each entry where the callback returns True.

        Raises:
            TypeError: If the provided callback is not a callable function.
        """
        if not callable(callback):
            raise TypeError("callback must be a callable function")

        for key, value in self._data.items():
            if callback(key, value):
                yield (key, value)


class ConfigSource(ReadOnlyConfigSource):
    """
    A class for managing configuration data from a single backend.
    """

    def __init__(self, name: str, backend: ConfigBackend):
        """
        Initialize the configuration instance with the given backend manager.

        Args:
            name (str): The name of the configuration source.
            backend (decker.common.config.backend.ConfigBackend): An instance managing backend operations.
        """
        self._backend: ConfigBackend
        super().__init__(name, backend)

    def load(self):
        """Load configuration data from the backend."""
        data = self._backend.load()
        self._data = flatten_dict.flatten(data, reducer="dot")

    def save(self):
        """Saves the current configuration data to the backend storage."""
        data: dict[str, Any] = flatten_dict.unflatten(self._data, splitter="dot")
        self._backend.save(data)

    def set(self, key: str, value: ValueType) -> None:
        """
        Sets a configuration key with the provided value. If any parent key exists, a ConfigurationKeyExists
        exception is raised.

        Parameters:
            key (str): The configuration key to set.
            value (ValueType): The value to associate with the key.

        Raises:
            ConfigurationKeyExists: If a parent key of the given key already exists in the configuration data.
            InvalidConfigurationValue: If the value is not of a valid type.
        """
        self.__setitem__(key, value)

    def __setitem__(self, key: str, value: ValueType) -> None:
        """
        Assign a configuration value using dictionary-like item assignment.

        Parameters:
            key (str): The key identifying the configuration setting.
            value (ValueType): The value to assign to the key.

        Returns:
            None
        """
        if not is_valid_value_type(value):
            raise InvalidConfigurationValue(
                f"Value for {key} is not a valid type must be one of "
                "{str, int, float, list, complex, set, bool, bytes, bytearray, datetime.datetime}"
            )

        paths = key.split(".")
        for i in range(1, len(paths)):
            parent_key = ".".join(paths[:i])
            if parent_key in self._data:
                raise ConfigurationKeyExists(
                    f"Can't add key {key}: parent key {parent_key} is already in the dictionary"
                )

        if isinstance(value, bytes):
            value_str = value.decode("utf-8")
        else:
            value_str = str(value)
        logging.debug("Setting configuration key %s to %s", key, value_str)
        self._data[key] = value
        self.save()

    def unset(self, key: str) -> None:
        """
        Remove configuration key(s) that match the provided key.

        Parameters:
            key (str): The base key or key prefix identifying the configuration entries to be removed.
        """
        self.__delitem__(key)

    def __delitem__(self, key: str) -> None:
        """
        Remove a configuration key using dictionary-like item deletion.

        Parameters:
            key (str): The key identifying the configuration setting to remove.

        Returns:
            None
        """
        keys = [key for key, _ in self.items(key)]
        remove = False

        for k in keys:
            logging.debug("Removing configuration key %s", k)
            self._data.pop(k)
            remove = True

        if remove:
            self.save()


class Config:
    """
    A class for managing configuration data that can be loaded from and saved to a backend(s).
    """

    def __init__(self):
        """Initialize the configuration instance with the given backend manager."""
        self._sources: list[ReadOnlyConfigSource | ConfigSource] = []

    def load(self):
        """Load configuration data from the backend."""
        for source in self._sources:
            source.load()
            # FIXME: Validate that the configuration data is valid when loading before loading the data

    def save(self):
        """Saves the current configuration data to the backend storage."""
        for s in self._sources:
            if isinstance(s, ConfigSource):
                s.save()
            else:
                logging.warning("Skipping save for read-only source: %s", s)

    def add_source(self, name, source: ReadOnlyConfigSource | ConfigSource) -> None:
        """
        Add a configuration source to the configuration manager.

        Parameters:
            name (str): The name of the source.
            source (ReadOnlyConfigSource | ConfigSource): The source to add.

        Raises:
            ValueError: If a source with the same name already exists.
        """
        if self.has_source(name):
            raise ValueError(f"Source with name '{name}' already exists.")

        data = self.list()
        new_source_data = source.list()

        return self._sources.insert(0, source)

    def get_sources(self) -> list[ReadOnlyConfigSource | ConfigSource]:
        """Retrieve all configuration sources."""
        return list(self._sources)

    def get_source(self, name: str) -> ReadOnlyConfigSource | ConfigSource:
        """
        Retrieve a configuration source by its name.

        Parameters:
            name (str): The name of the source to retrieve.

        Returns:
            ReadOnlyConfigSource | ConfigSource: The requested configuration source.

        Raises:
            KeyError: If no source with the given name exists.
        """
        for source in self._sources:
            if source.name == name:
                return source
        raise KeyError(f"No source found with name '{name}'.")

    def has_source(self, name: str) -> bool:
        """
        Check if a configuration source with the given name exists.

        Parameters:
            name (str): The name of the source to check.

        Returns:
            bool: True if the source exists, otherwise False.
        """
        for source in self._sources:
            if source.name == name:
                return True
        return False

    def has(self, key: str) -> bool:
        """Check if the given key exists within the internal configuration data.

        Args:
            key (str): The key to search for in the configuration data.

        Returns:
            bool: True if the key is found in the configuration data, otherwise False.
        """
        for source in self._sources:
            if source.has(key):
                return True
        return False

    def get(self, key: str) -> ValueType:
        """
        Retrieve the configuration value for the given key.

        Parameters:
            key (str): The key for which to retrieve the configuration value.

        Returns:
            ValueType: The value associated with the key if it exists.

        Raises:
            KeyError: If the key is not found in the collection.
        """
        for source in self._sources:
            if source.has(key):
                logging.debug("Found key %s in source %s", key, source.name)
                return source.get(key)
        raise KeyError(f"Key '{key}' not found in any configuration source.")

    def _source_supports_set(self, source: ReadOnlyConfigSource | ConfigSource) -> bool:
        """Check if the source supports setting values."""
        return hasattr(source, "set") and callable(getattr(source, "set"))

    def set(self, key: str, value: ValueType) -> None:
        """
        Sets a configuration key with the provided value.

        Parameters:
            key (str): The configuration key to set.
            value (ValueType): The value to associate with the key.

        Raises:
            ConfigurationKeyExists: If a parent key of the given key already exists in the configuration data.
            InvalidConfigurationValue: If the value is not of a valid type.
        """
        if not is_valid_value_type(value):
            raise InvalidConfigurationValue(
                f"Value for {key} is not a valid type must be one of "
                "{str, int, float, list, complex, set, bool, bytes, bytearray, datetime.datetime}"
            )

        # FIXME: check if key is either a parent key or a sub-key of an existing key if so refuse to add
        for source in self._sources:
            if isinstance(source, ReadOnlyConfigSource) or not self._source_supports_set(source):
                continue
            try:
                source.set(key, value)
                logging.debug("Set key %s to %s in source %s", key, value, source.name)
                break
            except ConfigurationKeyExists:
                logging.debug("Unable to set key %s in source %s", key, source.name)
                continue

    def unset(self, key: str) -> None:
        """
        Remove configuration key(s) that match the provided key.

        Parameters:
            key (str): The base key or key prefix identifying the configuration entries to be removed.
        """
        for source in self._sources:
            if isinstance(source, ReadOnlyConfigSource) or not self._source_supports_set(source):
                continue
            try:
                source.unset(key)
                logging.debug("Unset key %s in source %s", key, source.name)
                break
            except ConfigurationKeyExists:
                logging.debug("Unable to set key %s in source %s", key, source.name)
                continue

    def list(self, key: str | None = None) -> list[tuple[str, str, ValueType]]:
        """
        Retrieve configuration entries that match the provided key or its sub-keys.

        Parameters:
            key (str, Optional): The configuration key to filter by. If None, all entries are returned.

        Returns:
            list[tuple[str, str, ValueType]]: A list of tuples containing key, source name, and value.
        """
        merged_data: list[tuple[str, str, ValueType]] = []
        keys: list[str] = []

        for source in self._sources:
            data = source.list(key)
            for k, v in data:
                if k not in keys:
                    keys.append(k)
                    merged_data.append((k, source.name, v))

        return merged_data

    def __getitem__(self, key: str) -> ValueType:
        """Retrieve the value associated with the given key."""
        return self.get(key)

    def __setitem__(self, key: str, value: ValueType) -> None:
        """Assign a configuration value using dictionary-like item assignment."""
        self.set(key, value)

    def find(self, callback: Callable[[str, ValueType], bool]) -> Generator[tuple[str, ValueType], None, None]:
        """
        Iterates over the internal data dictionary and yields key-value pairs for which the provided callback
        returns True.

        Parameters:
            callback (Callable[[str, ValueType], bool]): A function that takes a key and a value from the
                internal data dictionary and returns a boolean.

        Yields:
            tuple[str, ValueType]: A tuple containing a key and its corresponding value.

        Raises:
            TypeError: If the provided callback is not a callable function.
        """
        # FIXME
        if not callable(callback):
            raise TypeError("callback must be a callable function")

        for key, value in self._data.items():
            if callback(key, value):
                yield key, value


class InvalidConfigurationValue(Exception):
    """
    Exception raised when an invalid configuration value is encountered.

    Attributes:
        message (Optional[str]): An optional error message providing details about the invalid value.
                                Defaults to "Invalid configuration value" if not provided.
    """

    def __init__(self, message: str | None = None):
        super().__init__(message or "Invalid configuration value")


class ConfigurationKeyExists(Exception):
    """
    Exception raised when a configuration key already exists.

    Parameters:
        message (str, optional):
            An optional string providing additional details about the error.
    """

    def __init__(self, message: str | None = None):
        super().__init__(message or "Key already exists in the configuration")


# Initialize configuration with default backend
user_config_path = os.path.expanduser(USER_CONFIG_FILE)
if not os.path.exists(user_config_path):
    with open(user_config_path, "w", encoding="utf-8") as config_file:
        config_file.write("")
