"""Fake executables that run on every platform."""

import sys
from pathlib import Path


def fake_executable(path: Path, python_source: str) -> Path:
    """Write a fake program and return the path to run it (a `.cmd` wrapper on Windows)."""
    if sys.platform == "win32":
        script = path.with_name(path.name + ".py")
        script.write_text(python_source)
        wrapper = path.with_name(path.name + ".cmd")
        wrapper.write_text(f'@"{sys.executable}" "{script}" %*\r\n')
        return wrapper
    path.write_text(f"#!{sys.executable}\n{python_source}")
    path.chmod(0o755)
    return path
