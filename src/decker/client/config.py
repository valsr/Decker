"""Configuration helper"""

import decker.common.config


CONFIG_SERVER_HOST = "client.host"
CONFIG_SERVER_PORT = "client.port"


def get_server() -> str:
    return decker.common.config.get_as(CONFIG_SERVER_HOST, str)

def get_port() -> int:
    return decker.common.config.get_as(CONFIG_SERVER_PORT, int)
