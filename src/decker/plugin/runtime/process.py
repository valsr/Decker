"""Server-side wrapper around one plugin child process."""

import logging
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO

from decker.plugin.protocol import (
    MAX_LINE_BYTES,
    Message,
    ProtocolError,
    decode,
    encode,
)

logger = logging.getLogger(__name__)

_DISCARD_CHUNK = 64 * 1024


class PluginProcess:
    """One plugin child process speaking newline-delimited JSON on stdin/stdout."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        plugin_id: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str],
        on_message: Callable[[Message], None],
        on_exit: Callable[[int], None],
    ) -> None:
        self._plugin_id = plugin_id
        self._command = command
        self._cwd = cwd
        self._env = env
        self._on_message = on_message
        self._on_exit = on_exit
        self._proc: subprocess.Popen[bytes] | None = None
        self._write_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    @property
    def is_running(self) -> bool:
        """True while the child process is alive."""
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        """PID of the child process, if it was started."""
        return self._proc.pid if self._proc is not None else None

    def start(self) -> None:
        """Spawn the child and its reader and watcher threads."""
        # pylint: disable-next=consider-using-with
        proc = subprocess.Popen(
            self._command,
            cwd=self._cwd,
            env=self._env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._proc = proc
        assert proc.stdout is not None and proc.stderr is not None
        readers = [
            threading.Thread(target=self._read_stdout, args=(proc.stdout,), daemon=True),
            threading.Thread(target=self._read_stderr, args=(proc.stderr,), daemon=True),
        ]
        for reader in readers:
            reader.start()
        self._threads = readers
        threading.Thread(target=self._watch, args=(proc, readers), daemon=True).start()

    def send(self, message: Message) -> None:
        """Write a message to the child; a no-op if it is not running."""
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return
        data = encode(message)
        try:
            with self._write_lock:
                proc.stdin.write(data)
                proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            logger.debug("[%s] could not send %s: %s", self._plugin_id, message.event, exc)

    def stop(self, timeout: float = 3.0) -> None:
        """Ask the child to shut down, then terminate, then kill it."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self.send(Message("shutdown"))
        self._close_stdin(proc)
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.kill()
        proc.wait()

    def rss_bytes(self) -> int | None:
        """Resident set size of the child from /proc, or None if unavailable."""
        if not self.is_running:
            return None
        try:
            with open(f"/proc/{self.pid}/status", encoding="ascii", errors="replace") as status:
                for line in status:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None

    def _close_stdin(self, proc: subprocess.Popen[bytes]) -> None:
        try:
            with self._write_lock:
                if proc.stdin is not None:
                    proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    def _read_stdout(self, stream: IO[bytes]) -> None:
        while True:
            line = stream.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
                logger.warning("[%s] oversized output line discarded", self._plugin_id)
                self._discard_rest(stream)
                continue
            self._dispatch(line)

    @staticmethod
    def _discard_rest(stream: IO[bytes]) -> None:
        while True:
            chunk = stream.readline(_DISCARD_CHUNK)
            if not chunk or chunk.endswith(b"\n"):
                return

    def _dispatch(self, line: bytes) -> None:
        try:
            message = decode(line.rstrip(b"\r\n"))
        except ProtocolError as exc:
            text = line.decode("utf-8", errors="replace").rstrip()
            logger.warning("[%s] non-protocol output: %s (%s)", self._plugin_id, text[:200], exc)
            return
        try:
            self._on_message(message)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("[%s] message handler failed for %s", self._plugin_id, message.event)

    def _read_stderr(self, stream: IO[bytes]) -> None:
        for raw in iter(stream.readline, b""):
            logger.info("[%s] %s", self._plugin_id, raw.decode("utf-8", errors="replace").rstrip())

    def _watch(self, proc: subprocess.Popen[bytes], readers: list[threading.Thread]) -> None:
        returncode = proc.wait()
        for reader in readers:
            reader.join()
        try:
            self._on_exit(returncode)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("[%s] exit handler failed", self._plugin_id)
