"""Typed accessors for client configuration keys."""

from decker.common import config

CONFIG_SERVER_HOST = "client.server_host"
CONFIG_SERVER_PORT = "client.server_port"


def get_server_host() -> str:
    """Return the configured server hostname."""
    return config.get_as(CONFIG_SERVER_HOST, str)


def get_server_port() -> int:
    """Return the configured server port."""
    return config.get_as(CONFIG_SERVER_PORT, int)


def set_server(host: str, port: int) -> None:
    """Persist the server hostname and port to the user config layer."""
    config.set(CONFIG_SERVER_HOST, host)
    config.set(CONFIG_SERVER_PORT, port)
