"""Build the command line and environment used to launch a plugin process."""

import os
import sys
from pathlib import Path

from decker.plugin.environment import venv_python
from decker.plugin.manifest import RuntimeSpec


def launch_command(plugin_dir: Path, runtime: RuntimeSpec) -> list[str]:
    """Return the argv for a plugin; the entry must resolve inside `plugin_dir`."""
    root = plugin_dir.resolve()
    entry = (root / runtime.entry).resolve()
    if not entry.is_relative_to(root):
        raise ValueError(f"entry '{runtime.entry}' resolves outside the plugin directory")
    if runtime.type == "executable":
        return [str(plugin_dir / runtime.entry)]
    python = str(venv_python(plugin_dir))
    return [python, "-m", "decker_plugin_sdk", str(plugin_dir / runtime.entry)]


_WINDOWS_VARS = (
    "SYSTEMROOT",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "COMSPEC",
    "PATHEXT",
)


def launch_env(sdk_path: Path | None) -> dict[str, str]:
    """Return a minimal environment for a plugin process."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONUNBUFFERED": "1",
    }
    if sys.platform == "win32":
        env.update({name: os.environ[name] for name in _WINDOWS_VARS if name in os.environ})
    if sdk_path is not None:
        env["PYTHONPATH"] = str(sdk_path)
    return env
