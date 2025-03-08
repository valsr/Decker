"""Linux specific functions for the decker server."""
import sys
from io import TextIOWrapper

if sys.platform == "linux":
    import fcntl

    def lock_file(lock_file: TextIOWrapper):
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock_file(lock_file: TextIOWrapper):
        fcntl.flock(lock_file, fcntl.LOCK_UN)
