"""Server-side wrapper around one plugin child process."""

import logging
import queue
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO

from decker.common import processes
from decker.plugin.protocol import (
    MAX_LINE_BYTES,
    Message,
    ProtocolError,
    decode,
    encode,
)

logger = logging.getLogger(__name__)

_DISCARD_CHUNK = 64 * 1024
_SEND_QUEUE_SIZE = 256
_STDERR_CHUNK = 8 * 1024
_READER_JOIN_SECONDS = 1.0


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
        self._outbox: queue.Queue[bytes] = queue.Queue(maxsize=_SEND_QUEUE_SIZE)
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
            **processes.group_popen_kwargs(),
        )
        self._proc = proc
        assert proc.stdout is not None and proc.stderr is not None
        readers = [
            threading.Thread(target=self._read_stdout, args=(proc.stdout,), daemon=True),
            threading.Thread(target=self._read_stderr, args=(proc.stderr,), daemon=True),
        ]
        writer = threading.Thread(target=self._write_loop, args=(proc,), daemon=True)
        readers.append(writer)
        for reader in readers:
            reader.start()
        self._threads = readers
        threading.Thread(target=self._watch, args=(proc, readers), daemon=True).start()

    def send(self, message: Message) -> None:
        """Queue a message for the child without blocking; dropped if not running or the queue is full."""
        if not self.is_running:
            return
        try:
            self._outbox.put_nowait(encode(message))
        except queue.Full:
            logger.warning("[%s] send queue full, dropping %s", self._plugin_id, message.event)

    def stop(self, timeout: float = 3.0) -> None:
        """Ask the child to shut down, then terminate, then kill it."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self.send(Message("shutdown"))
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        self._terminate_group()
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        self._kill_group()
        proc.wait()

    def _terminate_group(self) -> None:
        if self._proc is not None:
            processes.terminate_tree(self._proc)

    def _kill_group(self) -> None:
        if self._proc is not None:
            processes.kill_tree(self._proc)

    def rss_bytes(self) -> int | None:
        """Resident set size of the child, or None if unavailable."""
        if not self.is_running or self.pid is None:
            return None
        return processes.rss_bytes(self.pid)

    def _write_loop(self, proc: subprocess.Popen[bytes]) -> None:
        stdin = proc.stdin
        assert stdin is not None
        try:
            while proc.poll() is None:
                try:
                    data = self._outbox.get(timeout=0.2)
                except queue.Empty:
                    continue
                stdin.write(data)
                stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            logger.debug("[%s] stdin write stopped: %s", self._plugin_id, exc)
        finally:
            try:
                stdin.close()
            except (BrokenPipeError, ValueError, OSError):
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
        for raw in iter(lambda: stream.readline(_STDERR_CHUNK), b""):
            logger.info("[%s] %s", self._plugin_id, raw.decode("utf-8", errors="replace").rstrip())

    def _watch(self, proc: subprocess.Popen[bytes], readers: list[threading.Thread]) -> None:
        returncode = proc.wait()
        # A helper the plugin left behind can keep the pipes open forever; do not wait for it.
        for reader in readers:
            reader.join(timeout=_READER_JOIN_SECONDS)
        self._kill_group()
        try:
            self._on_exit(returncode)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("[%s] exit handler failed", self._plugin_id)
