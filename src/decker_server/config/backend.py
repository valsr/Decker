"""Configuration backends for loading and saving settings."""
import logging
import os
import threading
from typing import Any

import toml

CONFIG_KEY = "server"


class TomlFileBackend:
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

        This method reads the configuration file at self._path and verifies its existence and accessibility.
        If the file does not exist, it raises a FileNotFoundError. If the file is not readable, it raises a
        PermissionError. The file content is parsed with toml.load, and if the expected key (CONFIG_KEY) is not
        present in the loaded configuration, an empty dictionary is returned. Otherwise, the method returns the
        configuration data associated with CONFIG_KEY.

        Returns:
            dict[str, Any]: Parsed configuration data corresponding to CONFIG_KEY, or an empty dictionary if
            CONFIG_KEY is not found.

        Raises:
            FileNotFoundError: If the configuration file is not found at self._path.
            PermissionError: If the configuration file cannot be read.
        """
        if not os.path.exists(self._path):
            raise FileNotFoundError(f"Config file not found: {self._path}")
        if not os.access(self._path, os.R_OK):
            raise PermissionError(f"Cannot read config file: {self._path}")

        config_data = toml.load(self._path)
        if CONFIG_KEY not in config_data:
            return {}

        return config_data[CONFIG_KEY]

    def save(self, settings: dict[str, Any]) -> None:
        """
        Saves configuration settings to a file in TOML format.

        This method reads the existing configuration file if it exists and is readable,
        updates its "server" key with the provided settings, and writes the updated configuration
        back to the file. If the file exists but is not readable, a PermissionError is raised.

        Parameters:
            settings (dict[str, Any]): A dictionary containing the server configuration settings.

        Raises:
            PermissionError: If the configuration file exists but cannot be read.
        """
        config_data = {}
        if os.path.exists(self._path):
            if not os.access(self._path, os.R_OK):
                raise PermissionError(f"Cannot read config file: {self._path}")
            config_data = toml.load(self._path)

        config_data["server"] = settings
        with open(self._path, "w", encoding="UTF-8") as file:
            toml.dump(config_data, file)


class BackendManager:
    """BackendManager

    This class is responsible for managing configuration settings with thread-safe operations. It interacts
    with a TOML file backend to load and save configuration data, providing mechanisms to ensure that
    concurrent access is properly managed.
    """

    def __init__(self, backend: TomlFileBackend):
        """
        Initialize a new instance of the configuration class.

        This constructor sets up the configuration backend, along with a thread holder and a reentrant lock
        for synchronization.

        Parameters:
            backend (TomlFileBackend): An instance used to manage configuration data.
        """
        self._backend = backend
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any]:
        """Loads the settings in a thread-safe manner.

        This method clears any previously loaded data by calling flush, then starts a background worker thread
        to load the settings from the backend. It waits for the thread to finish execution before returning the
        result.

        Returns:
            dict[str, Any]: A dictionary containing the loaded settings.
        """
        with self._lock:
            self.flush()
            logging.debug("Starting new load thread")
            thread = LoadSettingsWorker(self._backend)
            self._thread = thread
            thread.start()
        thread.join()
        return thread.settings

    def save(self, settings: dict[str, Any]) -> None:
        """
        Saves the provided configuration settings asynchronously.

        This method first flushes any pending changes before starting a new thread dedicated
        to saving the settings. By acquiring an internal lock, it ensures thread safety during
        the save operation. A debug log is generated to indicate the start of the save thread.

        Args:
            settings (dict[str, Any]): A dictionary containing the configuration settings to be saved.

        Returns:
            None
        """
        with self._lock:
            self.flush()
            logging.debug("Starting new save thread")
            self._thread = SaveSettingsWorker(self._backend, settings)
            self._thread.start()

    def flush(self) -> None:
        """Wait for any remaining operations to complete."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                logging.debug("Waiting for previous task to finish")
                self._thread.join()


class LoadSettingsWorker(threading.Thread):
    """
    LoadSettingsWorker is a threaded worker responsible for loading configuration settings
    from a specified TOML file backend.
    """

    def __init__(self, backend: TomlFileBackend):
        """
        Initialize a new instance of the configuration class with the specified TOML file backend.

        Parameters:
            backend (TomlFileBackend): The backend instance used for reading and writing configuration files.
        """
        super().__init__()
        self._backend = backend
        self.settings: dict[str, Any] = {}

    def run(self):
        logging.debug("Running load settings worker")
        self.settings = self._backend.load()
        logging.debug("Load settings worker finished")


class SaveSettingsWorker(threading.Thread):
    """
    Worker thread responsible for saving configuration settings asynchronously.

    This thread leverages a provided backend (implementing a save method) to persist the given settings.
    It logs the beginning and end of the save operation to assist with debugging.
    """

    def __init__(self, backend: TomlFileBackend, settings: dict[str, Any]):
        """
        Initialize the configuration.

        Args:
            backend (TomlFileBackend): An instance responsible for handling the configuration storage.
            settings (dict[str, Any]): A dictionary containing configuration settings.
        """
        super().__init__()
        self._backend = backend
        self._settings = settings

    def run(self):
        logging.debug("Running save settings worker")
        self._backend.save(self._settings)
        logging.debug("Save settings worker finished")
