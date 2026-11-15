"""Per-plugin Python environments (built with uv) and SDK staging."""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Callable, Sequence
from importlib import metadata
from pathlib import Path

import decker_plugin_sdk
from decker.common import paths
from decker.plugin.manifest import RuntimeSpec

_TIMEOUT_SECONDS = 300
_TAIL_LINES = 20


class EnvironmentBuildError(Exception):
    """Raised when a plugin environment cannot be built."""


def _decker_version() -> str:
    try:
        return metadata.version("decker")
    except metadata.PackageNotFoundError:
        return "0"


def stage_sdk(dest_root: Path | None = None) -> Path:
    """Copy the plugin SDK to ``<root>/<decker version>/`` and return that directory (the PYTHONPATH entry)."""
    root = dest_root if dest_root is not None else paths.sdk()
    version_dir = root / _decker_version()
    target = version_dir / "decker_plugin_sdk"
    if target.exists():
        return version_dir
    source = Path(decker_plugin_sdk.__file__).parent
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
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
        )
    except OSError as exc:
        raise EnvironmentBuildError(f"cannot run {command[0]}: {exc}") from exc
    timer = threading.Timer(_TIMEOUT_SECONDS, proc.kill)
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
        proc.kill()
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
    python = runtime.python if runtime.python is not None else sys.executable
    _run([uv, "venv", str(venv), "--python", python], progress)
    if runtime.requirements:
        _run(
            [uv, "pip", "install", "--python", str(venv / "bin" / "python"), *extra_args, *runtime.requirements],
            progress,
        )
