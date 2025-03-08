"""OS agnostic functions for the decker server."""

import sys
from io import TextIOWrapper

if sys.platform == "win32":
    from . import windows as platform
else:
    from . import linux as platform

def lock_file(file: TextIOWrapper):
    """
    Lock the specified file to prevent concurrent access.

    This is a wrapper function for the platform-specific file locking implementation.

    Args:
        file (TextIOWrapper): An opened file object to be locked.

    Returns:
        The result of the platform-specific file locking operation.
        (The exact return type depends on the underlying platform implementation)

    Note:
        The behavior may vary depending on the operating system.
    """
    return platform.lock_file(file)


def unlock_file(file: TextIOWrapper):
    """
    Unlocks a file that was previously locked.

    This is a wrapper function for the platform-specific file unlocking implementation.

    Args:
        file (TextIOWrapper): The file object to unlock.

    Returns:
        The result of the platform-specific unlock_file operation.
    """
    return platform.unlock_file(file)
