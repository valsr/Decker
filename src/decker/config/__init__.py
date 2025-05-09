"""Module for managing application configurations."""

import builtins
import datetime
import logging
import os
from typing import Any, Callable, Generator, TypeVar, cast

import flatten_dict

from decker.config.backend import BackendManager, TomlFileBackend

ValueType = (
    str
    | int
    | float
    | complex
    | list
    | set  # pylint: disable=used-before-assignment
    | frozenset
    | bool
    | bytes
    | bytearray
    | datetime.datetime
)

T = TypeVar("T", bound=ValueType)

KEY_SEPARATOR = "."
USER_CONFIG_FILE = "~/.decker"


class Config:
    """
    A class for managing configuration data that can be loaded from and saved to a backend.
    """

    def __init__(self, backend: BackendManager):
        """
        Initialize the configuration instance with the given backend manager.

        Args:
            backend (decker.config.backend.BackendManager): An instance managing backend operations.
        """
        self._backend = backend
        self._data: dict[str, Any] = {}  # flat dictionary

    def load(self):
        """
        Load configuration data from the backend.
        """
        data = self._backend.load()
        self._data = flatten_dict.flatten(data, reducer="dot")

    def save(self):
        """
        Saves the current configuration data to the backend storage.
        """
        data = flatten_dict.unflatten(self._data, splitter="dot")
        self._backend.save(data)

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
        return self._data[key]

    def set(self, key: str, value: ValueType) -> None:
        """
        Sets a configuration key with the provided value. If any parent key exists, a ConfigurationKeyExists
        exception is raised.

        Parameters:
            key (str): The configuration key to set.
            value (ValueType): The value to associate with the key. It must be one of the accepted types.

        Raises:
            ConfigurationKeyExists: If a parent key of the given key already exists in the configuration data.
            InvalidConfigurationValue: If the value is not of a valid type.
        """
        if not isinstance(value, ValueType):
            raise InvalidConfigurationValue(
                f"Value for {key} is not a valid type must be one of "
                "{str, int, float, list, complex, set, bool, bytes, bytearray, datetime.datetime}"
            )

        # if key or any of the parent keys are in the dictionary, don't add
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

        This method retrieves all configuration keys that match or are sub-keys from the given key,

        Parameters:
            key (str): The base key or key prefix identifying the configuration entries to be removed.

        Side Effects:
            Modifies the internal configuration data by deleting matching keys.
            Triggers a save operation if any key has been removed.
        """
        keys = [key for key, _ in self.list(key)]
        remove = False

        for k in keys:
            logging.debug("Removing configuration key %s", k)
            self._data.pop(k)
            remove = True

        if remove:
            self.save()

    def list(self, key: str | None = None) -> list[tuple[str, ValueType]]:
        """
        Retrieve configuration entries that match the provided key or its sub-keys.

        Parameters:
            key (str, Optional): The configuration key to filter by. The search is case-insensitive. If None,
                all configuration entries are returned.

        Returns:
            list[tuple[str, ValueType]]: A list of tuples, where each tuple contains a key and its associated
                value.
        """
        if not key:
            return list(self._data.items())

        return [(k, v) for k, v in self._data.items() if k == key or k.startswith(key + KEY_SEPARATOR)]

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
        data = self.get(key)
        if data is None:
            raise KeyError(f"Key {key} not found")
        return data

    def __setitem__(self, key: str, value: ValueType) -> None:
        """
        Assign a configuration value using dictionary-like item assignment.

        This method enables setting a configuration value by using the syntax:
            obj[key] = value
        It delegates the assignment to the internal set() method.

        Parameters:
            key (str): The key identifying the configuration setting.
            value (ValueType): The value to assign to the key.

        Returns:
            None
        """
        self.set(key, value)

    def find(self, callback: Callable[[str, ValueType], bool]) -> Generator[tuple[str, ValueType], None, None]:
        """
        Iterates over the internal data dictionary and yields key-value pairs for which the provided callback
        returns True.

        Parameters:
            callback (Callable[[str, ValueType], bool]): A function that takes a key and a value from the
                internal data dictionary and returns a boolean. If it returns True, the key-value pair is
                yielded.

        Yields:
            tuple[str, ValueType]: A tuple containing a key and its corresponding value from the internal
                data dictionary for each entry where the callback returns True.

        Raises:
            TypeError: If the provided callback is not a callable function.
        """
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

    This exception is used to indicate that an attempt to add a duplicate key to the configuration has
    occurred. If no custom error message is provided, the default message "Key already exists in the
    configuration" is used.

    Parameters:
        message (str, optional):
            An optional string providing additional details about the error.
    """

    def __init__(self, message: str | None = None):
        super().__init__(message or "Key already exists in the configuration")


# Initialize configuration with default backend
user_config_path = os.path.expanduser(USER_CONFIG_FILE)
if not os.path.exists(user_config_path):
    # Create the user configuration file if it does not exist
    with open(user_config_path, "w", encoding="utf-8") as config_file:
        config_file.write("")

CONFIG: Config = Config(BackendManager(TomlFileBackend(user_config_path)))
"""The global configuration instance."""
CONFIG.load()


def load():
    """
    Load configuration data.
    """
    CONFIG.load()


def save() -> None:
    """
    Saves the current configuration.
    """
    CONFIG.save()


def has(key: str) -> bool:
    """Check if the given key exists within the configuration.

    Args:
        key (str): The key to search for.

    Returns:
        bool: True if the key is found in the configuration, otherwise False.
    """
    return CONFIG.has(key)


def get(key: str) -> ValueType | None:
    """
    Retrieve the configuration value for the given key.

    Parameters:
        key (str): The key for which to retrieve the configuration value.

    Returns:
        Optional[ValueType]: The value associated with the key if it exists; otherwise, None.
    """
    return CONFIG.get(key)


def get_as(key: str, target_type: type[T]) -> T:
    """
    Retrieve the configuration value for the given key and convert it to the specified target type.

    Parameters:
        key (str): The key for which to retrieve the configuration value.
        target_type (type): The type to convert the value to.

    Returns:
        The converted value of the specified type.

    Raises:
        TypeError: If the value is None or unable to conver to proper type
    """
    return to_type(get(key), target_type)


def get_as_or_default(key: str, target_type: type[T], default: T) -> T:
    """
    Retrieve the configuration value for the given key and convert it to the specified target type.

    Parameters:
        key (str): The key for which to retrieve the configuration value.
        target_type (type): The type to convert the value to.
        default: The default value to return if conversion fails.

    Returns:
        The converted value of the specified type, or the default value if conversion fails.
    """
    try:
        return to_type_or_default(get(key), target_type, default)
    except KeyError:
        return default


def set(key: str, value: ValueType) -> None:  # pylint: disable=redefined-builtin
    """
    Sets a configuration key with the provided value. If any parent key exists, a ConfigurationKeyExists
    exception is raised.

    Parameters:
        key (str): The configuration key to set
        value (ValueType): The value to associate with the key. It must be one of the accepted types.

    Raises:
        ConfigurationKeyExists: If a parent key of the given key already exists in the configuration data.
        InvalidConfigurationValue: If the value is not of a valid type.
    """
    CONFIG.set(key, value)


def unset(key: str) -> None:
    """
    Remove configuration key(s) that match the provided key.

    This method retrieves all configuration keys that match or are sub-keys from the given key,

    Parameters:
        key (str): The base key or key prefix identifying the configuration entries to be removed.

    Side Effects:
        Modifies the internal configuration data by deleting matching keys.
        Triggers a save operation if any key has been removed.
    """
    CONFIG.unset(key)


def items(key: str | None = None) -> list[tuple[str, ValueType]]:
    """
    Retrieve configuration entries that match the provided key or its sub-keys.

    Parameters:
        key (str, Optional): The configuration key to filter by. The search is case-insensitive. If None,
            all configuration entries are returned.

    Returns:
        list[tuple[str, ValueType]]: A list of tuples, where each tuple contains a key and its associated value.
    """
    return CONFIG.list(key)


def find(callback: Callable[[str, ValueType], bool]) -> Generator[tuple[str, ValueType], None, None]:
    """
    Iterates over the internal data dictionary and yields key-value pairs for which the provided callback
    returns True.

    Parameters:
        callback (Callable[[str, ValueType], bool]): A function that takes a key and a value from the
            internal data dictionary and returns a boolean. If it returns True, the key-value pair is
            yielded.

    Yields:
        tuple[str, ValueType]: A tuple containing a key and its corresponding value from the internal
            data dictionary for each entry where the callback returns True.

    Raises:
        TypeError: If the provided callback is not a callable function.
    """
    return CONFIG.find(callback)


def decode_value(value: ValueType | None):
    """
    Convert a configuration value to a string representation.

    Args:
        value: The configuration value to convert.

    Returns:
        str: A string representation of the configuration value.
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8")
    return str(value)


def value_type_to_string(value: ValueType | None) -> str:
    """
    Convert a configuration value to a string.

    Args:
        value: The configuration value to convert.

    Returns:
        str: The converted value as a string.
    """
    if value is None:
        return ""
    if isinstance(value, (list, builtins.set, frozenset)):
        raise TypeError(f"Cannot convert {type(value)} to str")

    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def value_type_to_bytes(value: ValueType | None) -> bytes:
    """
    Convert a configuration value to bytes.

    Args:
        value: The configuration value to convert.

    Returns:
        bytes: The converted value as a bytes.
    """
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, bytes):
        return value

    if isinstance(value, (list, builtins.set, frozenset)):
        if all(isinstance(item, int) and 0 <= item <= 255 for item in value):
            return bytes(value)  # Create bytes object from iterable of integers
        raise TypeError(f"Cannot convert {type(value)} to bytes: all elements must be integers in range 0-255")

    return bytes(value_type_to_string(value).encode("utf-8"))


def value_type_to_bool(value: ValueType | None) -> bool:
    """
    Convert a configuration value to a boolean.

    Args:
        value: The configuration value to convert.

    Returns:
        bool: The converted value as a boolean.
    """
    if value is None:
        return False

    if isinstance(value, str):
        lower_value = value.lower()
        if lower_value in ("true", "yes", "y", "1"):
            return True
        if lower_value in ("false", "no", "n", "0"):
            return False
        raise ValueError(f"Cannot convert {value} to bool")
    return bool(value)


def value_type_to_datetime(value: ValueType | None) -> datetime.datetime:
    """
    Convert a configuration value to a datetime.

    Args:
        value: The configuration value to convert.

    Returns:
        datetime.datetime: The converted value as a datetime.
    """
    if value is None:
        raise ValueError("Value is None")
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value)

    raise TypeError(f"Cannot convert {type(value)} to datetime.datetime")


def value_type_to_int(value: ValueType | None) -> int:
    """
    Convert a configuration value to an integer.

    Args:
        value: The configuration value to convert.

    Returns:
        int: The converted value as an integer.
    """
    if value is None:
        raise ValueError("Value is None")

    if isinstance(value, (int, float, str)):
        return int(value)

    raise TypeError(f"Cannot convert {type(value)} to int")


def value_type_to_float(value: ValueType | None) -> float:
    """
    Convert a configuration value to a float.

    Args:
        value: The configuration value to convert.

    Returns:
        float: The converted value as a float.
    """
    if value is None:
        raise ValueError("Value is None")

    if isinstance(value, (int, float, str)):
        return float(value)

    raise TypeError(f"Cannot convert {type(value)} to float")


def value_type_to_complex(value: ValueType | None) -> complex:
    """
    Convert a configuration value to a complex number.

    Args:
        value: The configuration value to convert.

    Returns:
        complex: The converted value as a complex number.
    """
    if value is None:
        raise ValueError("Value is None")

    if isinstance(value, (int, float, complex, str)):
        return complex(value)

    raise TypeError(f"Cannot convert {type(value)} to complex")


def value_type_to_list(value: ValueType | None) -> list[Any]:
    """
    Convert a configuration value to a list.

    Args:
        value: The configuration value to convert.

    Returns:
        list: The converted value as a list.
    """
    if value is None:
        return []

    if isinstance(value, (list, builtins.set, frozenset)):
        return list(value)

    if isinstance(value, (str, bytes, bytearray)):
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        return [item.strip() for item in value.split(",")]

    return [value]


def to_type(value: ValueType | None, target_type: type[T]) -> T:
    """
    Convert a configuration value to the specified target type.

    Args:
        value: The configuration value to convert.
        target_type: The type to convert the value to.

    Returns:
        The converted value of the specified type.

    Raises:
        TypeError: If the value is None or unable to conver to proper type
    """
    array_types = (list, builtins.set, frozenset)

    # Handle specific type conversions
    if target_type == str:
        return cast(T, value_type_to_string(value))
    if target_type == bytes:
        return cast(T, value_type_to_bytes(value))
    if target_type == bytearray:
        return cast(T, bytearray(value_type_to_bytes(value)))
    if target_type == int:
        return cast(T, value_type_to_int(value))
    if target_type == float:
        return cast(T, value_type_to_float(value))
    if target_type == complex:
        return cast(T, value_type_to_complex(value))
    if target_type == bool:
        return cast(T, value_type_to_bool(value))
    if target_type == datetime.datetime:
        return cast(T, value_type_to_datetime(value))
    if target_type in array_types:
        if isinstance(value, array_types):
            return cast(T, value)
        list_items = value_type_to_list(value)
        if target_type == frozenset:
            return cast(T, frozenset(list_items))
        if target_type == builtins.set:
            return cast(T, builtins.set(list_items))
        return cast(T, list_items)

    raise TypeError(f"Cannot convert {type(value)} to {target_type}")


def to_type_or_default(value: ValueType | None, target_type: type[T], default: T) -> T:
    """
    Convert a configuration value to the specified target type.

    Args:
        value: The configuration value to convert.
        target_type: The type to convert the value to.
        default: The default value to return if conversion fails.

    Returns:
        The converted value of the specified type, or the default value if conversion fails.
    """
    if value is None:
        return default

    try:
        return to_type(value, target_type)
    except (ValueError, TypeError):
        return default


def get_config_path() -> str:
    """Get the path to the user configuration file.

    Returns:
        str: The path to the user configuration file.
    """
    return user_config_path
