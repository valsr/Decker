""" Theme related functionality - colours, styles, etc."""

from __future__ import annotations
from enum import Enum
import logging
import termcolor

FORCE_COLOR: bool = False  # needed for testing as termcolor does not work in CI


class Theme(Enum):
    """Represents the available themes for the application."""

    DARK = "dark"
    LIGHT = "light"


THEME: Theme = Theme.DARK


def set_theme(theme: Theme):
    """Sets the global theme for the application.

    Args:
        theme(Theme): The theme to set.
    """
    global THEME  # pylint: disable=global-statement
    THEME = theme
    logging.debug("Theme set to %s", theme.value)


def get_theme() -> Theme:
    """Returns the current theme for the application.

    Returns:
        Theme: The current theme.
    """
    return THEME


class Style(Enum):
    """Enum class representing different styles for text."""

    DEFAULT = "DEFAULT"
    PRIMARY = "P"
    PRIMARY_ALT = "PL"
    SECONDARY = "S"
    SECONDARY_ALT = "SL"
    HIGHLIGHT = "H"
    HIGHLIGHT_ALT = "HL"
    DEBUG = "D"
    INFO = "I"
    WARNING = "W"
    WARNING_ALT = "WL"
    ERROR = "E"
    ERROR_ALT = "EL"
    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    H4 = "H4"


def primary(text):
    """
    Colors the given text with the primary style.

    Args:
        text (str): The text to be colored.

    Returns:
        str: The colored text.
    """
    return colored(text, Style.PRIMARY)


def colored(text, style: Style = Style.PRIMARY):
    """Applies color to the given text based on the specified style and theme.

    Args:
        text(str): The text to be colored.
        style(Style): The style to be applied. Defaults to Style.PRIMARY.

    Returns:
        str: The colored text.
    """
    return termcolor.colored(text, get_style(style), force_color=FORCE_COLOR)


def secondary(text):
    """Formats the given text as secondary text using the specified theme.

    Args:
        text(str): The text to format as secondary text.

    Returns:
        str: The formatted secondary text.
    """
    return colored(text, Style.SECONDARY)


def h1(text):
    """Formats the given text as a level 1 heading (H1) using the specified theme.

    Args:
        text(str): The text to format as a heading.

    Returns:
        str: The formatted heading text.
    """
    return colored(text, Style.H1)


def h2(text):
    """Formats the given text as a level 2 heading (H2) using the specified theme.

    Args:
        text(str): The text to format as an H2 heading.

    Returns:
        str: The formatted H2 heading.
    """
    return colored(text, Style.H2)


def h3(text):
    """Formats the given text as a level 3 heading using the specified theme.

    Args:
        text(str): The text to format as a heading.

    Returns:
        str: The formatted heading text.
    """
    return colored(text, Style.H3)


def h4(text):
    """Formats the given text as a level 4 heading (H4) using the specified theme.

    Args:
        text(str): The text to format as a heading.

    Returns:
        str: The formatted heading text.
    """
    return colored(text, Style.H4)


def highlight(text):
    """Applies highlighting to the given text using the specified theme.

    Args:
        text(str): The text to be highlighted.

    Returns:
        str: The highlighted text.
    """
    return colored(text, Style.HIGHLIGHT)


def warning(text):
    """Displays a warning message with the specified text and theme.

    Args:
        text(str): The text to display as a warning.

    Returns:
        str: The formatted warning message.
    """
    return colored(text, Style.WARNING)


def error(text):
    """Formats the given text as an error message using the specified theme.

    Args:
        text(str): The text to format as an error message.

    Returns:
        str: The formatted error message.
    """
    return colored(text, Style.ERROR)


def get_style(style: Style):
    """Returns the style for a given theme.

    Args:
        style(Style): The style to apply.

    Returns:
        Style: The style for the given theme.
    """
    if get_theme() == Theme.LIGHT:
        return get_light_theme_style(style)
    return get_dark_theme_style(style)


def get_light_theme_style(style: Style):
    """Returns the corresponding color for the given style in the light theme.

    Args:
        style(Style): The style for which to retrieve the color.

    Returns:
        str: The color associated with the given style in the light theme.
    """
    if style in (Style.PRIMARY, Style.INFO):
        return "black"
    if style in (Style.PRIMARY_ALT, Style.DEBUG):
        return "dark_grey"
    if style in (Style.SECONDARY, Style.H1):
        return "green"
    if style in (Style.SECONDARY_ALT, Style.H4):
        return "light_green"
    if style in (Style.HIGHLIGHT, Style.H2):
        return "yellow"
    if style == Style.HIGHLIGHT_ALT:
        return "light_yellow"
    if style == Style.WARNING:
        return "yellow"
    if style == Style.WARNING_ALT:
        return "light_yellow"
    if style == Style.ERROR:
        return "red"
    if style == Style.ERROR_ALT:
        return "light_red"
    if style == Style.H3:
        return "blue"

    # Style default, all others
    return "black"


def get_dark_theme_style(style: Style):
    """Returns the corresponding color theme for the given style in a dark theme.

    Args:
        style(Style): The style for which to retrieve the color theme.

    Returns:
        str: The color theme corresponding to the given style in a dark theme.
    """
    if style in (Style.PRIMARY, Style.INFO):
        return "light_grey"
    if style in (Style.PRIMARY_ALT, Style.DEBUG):
        return "dark_grey"
    if style in (Style.SECONDARY, Style.H1):
        return "green"
    if style in (Style.SECONDARY_ALT, Style.H4):
        return "light_green"
    if style in (Style.HIGHLIGHT, Style.H2):
        return "light_blue"
    if style == Style.HIGHLIGHT_ALT:
        return "blue"
    if style in (Style.WARNING, Style.H3):
        return "light_yellow"
    if style == Style.WARNING_ALT:
        return "yellow"
    if style == Style.ERROR:
        return "light_red"
    if style == Style.ERROR_ALT:
        return "red"

    # Style default, all others
    return "light_grey"
