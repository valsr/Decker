"""Executables that run on every platform, so tests exercise the real launch path."""

import json
import sys
from pathlib import Path


def entry_name(script_name: str) -> str:
    """Return the launchable entry for a Python script: the script itself, or its `.cmd` wrapper on Windows."""
    return Path(script_name).with_suffix(".cmd").as_posix() if sys.platform == "win32" else script_name


def cmd_wrapper(script_name: str) -> str:
    """Return the `.cmd` text that runs a Python script sitting next to it with the current interpreter."""
    return f'@"{sys.executable}" "%~dp0{script_name}" %*\r\n'


def install_launcher(script: Path) -> Path:
    """Make an existing Python script launchable directly; return the path to launch."""
    if sys.platform == "win32":
        wrapper = script.with_suffix(".cmd")
        wrapper.write_text(cmd_wrapper(script.name))
        return wrapper
    script.chmod(0o755)
    return script


def fake_executable(path: Path, python_source: str) -> Path:
    """Write a fake program and return the path to run it (a `.cmd` wrapper on Windows)."""
    if sys.platform == "win32":
        script = path.with_name(path.name + ".py")
        script.write_text(python_source)
        return install_launcher(script)
    path.write_text(f"#!{sys.executable}\n{python_source}")
    return install_launcher(path)


def adapt_fixture_plugin(folder: Path) -> None:
    """On Windows, give a copied fixture plugin a `.cmd` entry and point its manifest at it."""
    if sys.platform != "win32":
        return
    manifest = folder / "manifest.json"
    data = json.loads(manifest.read_text())
    script = folder / data["runtime"]["entry"]
    data["runtime"]["entry"] = install_launcher(script).relative_to(folder).as_posix()
    manifest.write_text(json.dumps(data))
