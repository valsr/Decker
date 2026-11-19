"""Per-plugin Python environments (built with uv) and SDK staging."""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Sequence
from pathlib import Path

import decker_plugin_sdk
from decker.common import paths, processes
from decker.common.version import decker_version
from decker.plugin.manifest import RuntimeSpec

_TIMEOUT_SECONDS = 300
_TAIL_LINES = 20
_MIN_PYTHON = (3, 10)
_PLAIN_VERSION = re.compile(r"^\d+(\.\d+)*$")
_SPECIFIER = re.compile(r"^[<>=!~]")


def venv_python(plugin_dir: Path) -> Path:
    """Return the interpreter inside a plugin's ``.venv`` for the running platform."""
    venv = plugin_dir / ".venv"
    return venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"


class EnvironmentBuildError(Exception):
    """Raised when a plugin environment cannot be built."""


def _sdk_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(source)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _python_request(python: str | None) -> str:
    """Return the ``uv venv --python`` request, never allowing an interpreter older than the SDK supports."""
    floor = ".".join(str(n) for n in _MIN_PYTHON)
    if python is None:
        return sys.executable
    if _PLAIN_VERSION.match(python):
        if tuple(int(n) for n in python.split("."))[:2] < _MIN_PYTHON:
            raise EnvironmentBuildError(f"runtime.python {python!r} is older than the supported minimum {floor}")
        return python
    if _SPECIFIER.match(python):
        return f"{python},>={floor}"
    return python


def stage_sdk(dest_root: Path | None = None) -> Path:
    """Copy the plugin SDK to ``<root>/<decker version>/`` and return that directory (the PYTHONPATH entry)."""
    root = dest_root if dest_root is not None else paths.sdk()
    source = Path(decker_plugin_sdk.__file__).parent
    version_dir = root / f"{decker_version()}-{_sdk_digest(source)}"
    target = version_dir / "decker_plugin_sdk"
    if target.exists():
        return version_dir
    version_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".sdk-", dir=version_dir))
    try:
        shutil.copytree(source, tmp / "decker_plugin_sdk", ignore=shutil.ignore_patterns("__pycache__"))
        try:
            os.rename(tmp / "decker_plugin_sdk", target)
        except OSError:
            if not target.exists():
                raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    logging.info("Staged plugin SDK at %s", version_dir)
    return version_dir


def _run(command: list[str], progress: Callable[[str], None]) -> None:
    tail: deque[str] = deque(maxlen=_TAIL_LINES)
    try:
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            **processes.group_popen_kwargs(),
        )
    except OSError as exc:
        raise EnvironmentBuildError(f"cannot run {command[0]}: {exc}") from exc
    timer = threading.Timer(_TIMEOUT_SECONDS, processes.kill_tree, args=(proc,))
    timer.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.rstrip("\n")
            tail.append(text)
            progress(text)
        code = proc.wait()
        timed_out = not timer.is_alive()
    finally:
        timer.cancel()
        processes.kill_tree(proc)
        proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()
    if timed_out:
        raise EnvironmentBuildError(f"{command[0]} timed out after {_TIMEOUT_SECONDS}s\n" + "\n".join(tail))
    if code != 0:
        raise EnvironmentBuildError(f"{command[0]} failed (exit {code})\n" + "\n".join(tail))


def build_environment(
    plugin_dir: Path,
    runtime: RuntimeSpec,
    progress: Callable[[str], None],
    uv: str = "uv",
    *,
    extra_args: Sequence[str] = (),
) -> None:
    """Create ``<plugin_dir>/.venv`` and install the declared requirements into it."""
    venv = plugin_dir / ".venv"
    python = _python_request(runtime.python)
    _run([uv, "venv", "--relocatable", str(venv), "--python", python], progress)
    if runtime.requirements:
        _run(
            [uv, "pip", "install", "--python", str(venv_python(plugin_dir)), *extra_args, *runtime.requirements],
            progress,
        )
