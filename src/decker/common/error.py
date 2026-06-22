import logging
from typing import Never


def raise_logged(exc: Exception, log: bool = True, logger: logging.Logger | None = None) -> Never:
    """Raise exc, optionally logging it at ERROR level first.

    The log record points to the caller's line, not this function.
    """
    if log:
        (logger or logging.getLogger()).error(str(exc), stacklevel=2)
    raise exc


class DeckerError(Exception):
    """
    Custom exception class for Decker-related errors.

    This exception is raised when errors specific to the Decker application occur.
    It extends the built-in Exception class and stores a custom error message.

    Attributes:
        message (str): The error message describing what went wrong.

    Args:
        message (str): A descriptive error message.

    Example:
        >>> raise DeckerError("Configuration file not found")
        DeckerError: Configuration file not found
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)
