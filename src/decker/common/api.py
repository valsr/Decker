import dataclasses
import logging
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

import rpyc
import rpyc.utils.factory

T = TypeVar("T")


def _coerce(target_type: Any, value: Any) -> Any:
    """Recursively convert value to target_type, handling generics and dataclasses."""
    if value is None:
        return None

    origin = get_origin(target_type)
    type_args = get_args(target_type)

    if origin is list:
        items = list(value)
        return [_coerce(type_args[0], item) for item in items] if type_args else items

    if origin is dict:
        pairs = dict(value)
        if len(type_args) == 2:
            return {_coerce(type_args[0], k): _coerce(type_args[1], v) for k, v in pairs.items()}
        return pairs

    if origin is not None:
        logging.debug("_coerce: unsupported generic type %s, returning value as-is", origin)
        return value

    if not isinstance(target_type, type):
        return value

    if dataclasses.is_dataclass(target_type):
        if isinstance(value, target_type):
            return value
        if isinstance(value, dict):
            data = value
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            data = dataclasses.asdict(value)
        else:
            # RPyC netref — materialize by reading each field by name
            logging.warning("_coerce: value is a netref, materializing fields for %s", target_type)
            data = {f.name: getattr(value, f.name) for f in dataclasses.fields(target_type)}
        try:
            hints = get_type_hints(target_type)
        except Exception:  # pylint: disable=broad-except
            hints = {}
        valid = {f.name for f in dataclasses.fields(target_type)}
        return target_type(**{k: _coerce(hints[k], v) if k in hints else v for k, v in data.items() if k in valid})

    if isinstance(value, target_type):
        return value

    return target_type(value)


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
            v = _coerce(target_type, response)
            return v
        except Exception as exc:  # pylint: disable=broad-except
            name = getattr(target_type, "__name__", repr(target_type))
            logging.warning("Could not convert response to %s: %s", name, exc)
            return None


API = ApiHandler()
