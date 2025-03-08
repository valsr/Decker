"""Windows specific functions for the decker server."""
import sys
from io import TextIOWrapper

if sys.platform != "win32":
    sys.exit("This module is only supported on Windows platforms.")

import msvcrt  # pylint: disable=wrong-import-position,import-error


def lock_file(file: TextIOWrapper):
    """
    Lock the specified file to prevent concurrent access.

    This is for the Windows platform.

    Args:
        file (TextIOWrapper): An opened file object to be locked.

    Returns:
        The result of the platform-specific file locking operation.
        (The exact return type depends on the underlying platform implementation)

    Note:
        The behavior may vary depending on the operating system.
    """
    msvcrt.lock(file.fileno(), msvcrt.LK_NBLCK, 1)

def unlock_file(file: TextIOWrapper):
    """
    Unlocks a file that was previously locked.

    This is for the Windows platform.

    Args:
        file (TextIOWrapper): The file object to unlock.

    Returns:
        The result of the platform-specific unlock_file operation.
    """
    msvcrt.lock(file.fileno(), msvcrt.LK_UNLCK, 1)
