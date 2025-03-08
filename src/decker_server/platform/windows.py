"""Windows specific functions for the decker server."""

import sys
from io import TextIOWrapper

if sys.platform == "win32":
    import msvcrt

    def lock_file(lock_file: TextIOWrapper):
        msvcrt.lock(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

    def unlock_file(lock_file: TextIOWrapper):
        msvcrt.lock(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
