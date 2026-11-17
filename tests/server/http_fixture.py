"""Local HTTP server for tests: serves a directory with configurable delay and status."""

import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class _Handler(SimpleHTTPRequestHandler):
    server: "FixtureServer"

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        if self.server.delay:
            time.sleep(self.server.delay)
        if self.server.status != 200:
            self.send_error(self.server.status)
            return
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:  # pylint: disable=redefined-builtin
        pass


class FixtureServer(ThreadingHTTPServer):
    """Serves root over 127.0.0.1 on a free port; set delay (seconds) or status to inject faults."""

    daemon_threads = True

    def __init__(self, root: Path) -> None:
        super().__init__(("127.0.0.1", 0), partial(_Handler, directory=str(root)))
        self.delay: float = 0.0
        self.status: int = 200
        self._thread: threading.Thread = threading.Thread(target=self.serve_forever, daemon=True)

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # clients that give up early (timeouts, size limits) are expected

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> "FixtureServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
