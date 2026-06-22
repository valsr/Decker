import logging
from typing import Any, TypeVar

import rpyc
import rpyc.utils.factory

from decker.common.coerce import coerce

T = TypeVar("T")


class ApiHandler:
    def __init__(self, host: str | None = None, port: int | None = None, timeout: float = 2.0):
        self.host = host or "localhost"
        self.port = port or 18861
        self._timeout = timeout
        self._connection = None

    def __del__(self):
        """Clean up the connection when the object is destroyed."""
        if not self._connection:
            return

        logging.info("Closing connection to server at %s:%d", self.host, self.port)
        try:
            self._connection.close()
        except Exception:
            pass
        finally:
            self._connection = None

    def _init_connection(self):
        """Initialize the connection to the server."""
        if self._connection:
            return

        try:
            self._connection = rpyc.utils.factory.connect(
                self.host, self.port, config={"sync_request_timeout": self._timeout}
            )
            logging.info("Connected to server at %s:%d", self.host, self.port)
        except Exception as e:
            logging.error("Failed to connect to server: %s", e)
            raise

    def request(self, func_name: str, *args, **kwargs) -> None | Any:
        """Handle a request to the server by calling a remote function."""
        self._init_connection()
        if not self._connection:
            logging.error("No connection established.")
            return None

        remote_func = getattr(self._connection.root, func_name)
        response = remote_func(*args, **kwargs)
        return response

    def request_as(self, target_type: Any, func_name: str, *args, **kwargs) -> Any:
        """Call a remote function and deserialize the result into target_type.

        Supports plain types, dataclasses (from dict), and generic aliases such as
        list[SomeDataclass] or dict[str, SomeDataclass].
        Returns None if the response is None or conversion fails.
        """
        response = self.request(func_name, *args, **kwargs)
        if response is None:
            return None
        try:
            v = coerce(target_type, response)
            return v
        except Exception as exc:  # pylint: disable=broad-except
            name = getattr(target_type, "__name__", repr(target_type))
            logging.warning("Could not convert response to %s: %s", name, exc)
            return None


API = ApiHandler()
