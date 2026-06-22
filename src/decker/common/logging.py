"""Logging configuration and helper utilities."""

import logging
import os
import time
from typing import Any

from decker.common.theme import highlight, secondary, warning

LOG_LEVEL = logging.WARNING


def log_level() -> int:
    """Get the current configured log level.

    Returns:
        int: The corresponding log level.
    """
    return LOG_LEVEL


def is_debug() -> bool:
    """Check if the log level is set to debug.

    Returns:
        bool: True if the log level is set to debug, False otherwise.
    """
    return LOG_LEVEL == logging.DEBUG


def is_info() -> bool:
    """Check if the log level is set to info.

    Returns:
        bool: True if the log level is set to info, False otherwise.
    """
    return LOG_LEVEL == logging.INFO


def is_warning() -> bool:
    """Check if the log level is set to warning.

    Returns:
        bool: True if the log level is set to warning, False otherwise.
    """
    return LOG_LEVEL == logging.WARNING


class NamespaceFilter(logging.Filter):
    """Filter to add the full namespace to the log record."""

    def __init__(self):
        super().__init__()
        self.base_path = os.path.dirname(os.path.abspath(os.path.join(__file__, "..")))

    def filter(self, record: logging.LogRecord):
        if record.pathname.startswith(self.base_path):
            record.namespace = record.pathname[len(self.base_path) + 1 : -3].replace(os.path.sep, ".")
        else:
            record.namespace = f"Unknown module ({record.pathname})"
        return True


class _Formatter(logging.Formatter):
    """Logging formatter that uses '.' instead of ',' as the millisecond separator."""

    default_msec_format = "%s.%03d"


_CLI_FORMAT = "%(asctime)s %(levelname)s [%(namespace)s:%(lineno)d]: %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s [%(namespace)s:%(lineno)d] %(message)s"


def configure(
    level: int = logging.INFO,
    log_directory: str = "",
    server_id: str | None = None,
):
    """Configure global/default logger.

    Args:
        level(int): Log level. Defaults to logging.WARNING.
        log_directory(str): The directory to store log files. Defaults to "".
        server_id(str): The server ID (or None for the main process) to use in the log file name. Defaults to None.
    """
    global LOG_LEVEL  # pylint: disable=global-statement
    LOG_LEVEL = level  # pyright: ignore[reportConstantRedefinition]

    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)

    for handler in logger.handlers:
        logger.removeHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.addFilter(NamespaceFilter())
    stream_handler.setFormatter(_Formatter(_CLI_FORMAT))
    logger.addHandler(stream_handler)

    log_name = "decker-server" if server_id is None else f"decker-server-{server_id}"
    file_handler = logging.FileHandler(os.path.join(log_directory, f"{log_name}.log"))
    file_handler.addFilter(NamespaceFilter())
    file_handler.setFormatter(_Formatter(_FILE_FORMAT))
    logger.addHandler(file_handler)


class PerformanceLogger:
    """Performance logger - logs the time taken to execute the block of code it wraps."""

    def __init__(self, description: str, details: str | None = None, level: int = logging.DEBUG):
        """Initialize the performance logger.

        Args:
            description (str): The operation description being timed.
        """
        self.description = description
        self.start: float = 0
        self.details = details
        self.override_threshold = 10000
        self.warn_threshold = 1000
        self.enabled = True
        self.log_level = level

    def __enter__(self):
        """Start the timer."""
        self.start = time.time()
        if not self.enabled:
            return self
        logging.log(self.log_level, secondary(self.description))
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any):
        """Log the time taken to execute the block of code."""
        diff = time.time() - self.start
        should_log = self.enabled or diff > self.override_threshold or diff > self.warn_threshold
        if not should_log:
            return

        should_warn = diff > self.warn_threshold
        message: str = "seconds"
        if diff < 1.5:
            diff = diff * 1000
            message = "milliseconds"

        if should_warn:
            message = warning("[perf] Time to ") + secondary(self.description) + ": " + warning(f"{diff:.2f} {message}")
        else:
            message = "[perf] Time to " + secondary(self.description) + ": " + highlight(f"{diff:.2f} {message}")
        logging.log(logging.WARNING if should_warn else self.log_level, message)


LOGGED: list[str] = []


def log_once(key: str, level: int, message: str, *args: tuple[Any], **kwargs: dict[str, Any]):
    """Log a message only once.

    Args:
        key (str): The key to use to identify the message.
        message (str): The message to log.
    """
    if key not in LOGGED:
        logging.log(level, message, *args, **kwargs)  # type: ignore
        LOGGED.append(key)


def debug_once(key: str, message: str, *args: tuple[Any], **kwargs: dict[str, Any]):
    """Log a debug message only once.

    Args:
        key (str): The key to use to identify the message.
        message (str): The message to log.
    """
    log_once(key, logging.DEBUG, message, *args, **kwargs)


def info_once(key: str, message: str, *args: tuple[Any], **kwargs: dict[str, Any]):
    """Log an info message only once.

    Args:
        key (str): The key to use to identify the message.
        message (str): The message to log.
    """
    log_once(key, logging.INFO, message, *args, **kwargs)


def warning_once(key: str, message: str, *args: tuple[Any], **kwargs: dict[str, Any]):
    """Log a warning message only once.

    Args:
        key (str): The key to use to identify the message.
        message (str): The message to log.
    """
    log_once(key, logging.WARNING, message, *args, **kwargs)


def error_once(key: str, message: str, *args: tuple[Any], **kwargs: dict[str, Any]):
    """Log an error message only once.

    Args:
        key (str): The key to use to identify the message.
        message (str): The message to log.
    """
    log_once(key, logging.ERROR, message, *args, **kwargs)


def critical_once(key: str, message: str, *args: tuple[Any], **kwargs: dict[str, Any]):
    """Log a critical message only once.

    Args:
        key (str): The key to use to identify the message.
        message (str): The message to log.
    """
    log_once(key, logging.CRITICAL, message, *args, **kwargs)


class InfoPerformanceLogger(PerformanceLogger):
    """Performance logger - logs the time taken to execute the block of code it wraps."""

    def __init__(self, description: str, details: str | None = None):
        """Initialize the performance logger.

        Args:
            description (str): The operation description being timed.
        """
        super().__init__(description, details, logging.INFO)
