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


CONFIG_THEME = "client.theme"
CONFIG_STYLE_SHEET = "client.style_sheet"

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEME_CUSTOM = "custom"
THEMES = (THEME_DARK, THEME_LIGHT, THEME_CUSTOM)


def get_theme() -> str:
    """Return the configured theme name.

    Falls back to "custom" when only a custom stylesheet path is configured (the setting that
    predates theme selection), and to "dark" otherwise or when the configured name is unknown.
    """
    theme = config.get_as_or_default(CONFIG_THEME, str, "")
    if theme in THEMES:
        return theme
    return THEME_CUSTOM if get_custom_style_sheet() else THEME_DARK


def get_custom_style_sheet() -> str:
    """Return the configured custom stylesheet path, or an empty string if none is set."""
    return config.get_as_or_default(CONFIG_STYLE_SHEET, str, "")


def set_theme(theme: str, custom_style_sheet: str = "") -> None:
    """Persist the theme name and, for the custom theme, the stylesheet path."""
    if theme not in THEMES:
        raise ValueError(f"Unknown theme: {theme}")
    config.set(CONFIG_THEME, theme)
    if theme == THEME_CUSTOM:
        config.set(CONFIG_STYLE_SHEET, custom_style_sheet)
