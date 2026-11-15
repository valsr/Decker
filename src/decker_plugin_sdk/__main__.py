"""Entry point: python -m decker_plugin_sdk <entry.py>."""

import importlib.util
import sys
from typing import BinaryIO, cast

from ._runtime import registered_actions, run


def main(argv: list[str]) -> int:
    """Import the plugin entry file and run its actions over the real stdio."""
    if len(argv) != 2:
        print("usage: python -m decker_plugin_sdk <entry.py>", file=sys.stderr)
        return 2
    stdout = cast(BinaryIO, sys.__stdout__.buffer)  # type: ignore[union-attr]
    sys.stdout = sys.stderr  # stray prints must never corrupt the protocol stream
    spec = importlib.util.spec_from_file_location("decker_plugin_entry", argv[1])
    if spec is None or spec.loader is None:
        print(f"cannot load plugin entry {argv[1]}", file=sys.stderr)
        return 2
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return run(registered_actions(), cast(BinaryIO, sys.stdin.buffer), stdout)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
