"""OS agnostic functions for the decker server."""

import sys
from io import TextIOWrapper

if sys.platform == "win32":
    from . import windows as platform
else:
    from . import linux as platform

def lock_file(lock_file: TextIOWrapper):
    return platform.lock_file(lock_file)


def unlock_file(lock_file: TextIOWrapper):
    return platform.unlock_file(lock_file)
