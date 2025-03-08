"""Linux specific functions for the decker server."""
import sys
from io import TextIOWrapper

if sys.platform != "linux":
    sys.exit("This module is only supported on Linux platforms.")

import fcntl  # pylint: disable=wrong-import-position


def lock_file(file: TextIOWrapper):
    """
    Lock the specified file to prevent concurrent access.

    This is for the Linux platform.

    Args:
        file (TextIOWrapper): An opened file object to be locked.

    Returns:
        The result of the platform-specific file locking operation.
        (The exact return type depends on the underlying platform implementation)

    Note:
        The behavior may vary depending on the operating system.
    """
    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)

def unlock_file(file: TextIOWrapper):
    """
    Unlocks a file that was previously locked.

    This is for the Linux platform.

    Args:
        file (TextIOWrapper): The file object to unlock.

    Returns:
        The result of the platform-specific unlock_file operation.
    """
    fcntl.flock(file, fcntl.LOCK_UN)
