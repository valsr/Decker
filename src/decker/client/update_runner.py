"""Sequential repository installs/updates: one server job at a time, advanced by finished events."""

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

RESULT_OK = "ok"


class UpdateRunner:
    """Runs `plugin_install_from_repository` for a list of plugin ids, one job after another.

    Qt-free. Feed every `plugin_install_finished` event to `on_finished`; it may arrive before the start call
    returns the job id, in which case it is held and replayed.
    """

    def __init__(self, call: Callable[..., Any], on_complete: Callable[[dict[str, str]], None] | None = None) -> None:
        self._call = call
        self._on_complete = on_complete
        self._queue: deque[str] = deque()
        self._current: str | None = None
        self._job_id: str | None = None
        self._early: tuple[str, bool, str] | None = None
        self.results: dict[str, str] = {}

    @property
    def busy(self) -> bool:
        """Whether a run is in progress."""
        return self._current is not None

    def run(self, plugin_ids: list[str]) -> None:
        """Start a fresh run over plugin_ids; ignored while a run is in progress."""
        if self.busy:
            logging.warning("Plugin update run requested while another is in progress; ignored")
            return
        if not plugin_ids:
            return
        self.results = {}
        self._queue = deque(plugin_ids)
        self._advance()

    def on_finished(self, job_id: str, ok: bool, message: str) -> None:
        """Record the outcome of the current job and start the next one."""
        if self._current is None:
            return
        if self._job_id is None:
            self._early = (job_id, ok, message)
            return
        if job_id != self._job_id:
            return
        self._finish_current(ok, message)
        self._advance()

    def _finish_current(self, ok: bool, message: str) -> None:
        if self._current is None:
            return
        self.results[self._current] = RESULT_OK if ok else (message or "Install failed")
        self._current = None
        self._job_id = None

    def _advance(self) -> None:
        while self._queue:
            plugin_id = self._queue.popleft()
            self._current, self._job_id, self._early = plugin_id, None, None
            error = self._start(plugin_id)
            if error is not None:
                self.results[plugin_id] = error
                self._current = None
                continue
            if self._early is not None:
                early_job, ok, message = self._early
                self._early = None
                if early_job == self._job_id:
                    self._finish_current(ok, message)
                    continue
            return
        if self._on_complete is not None:
            self._on_complete(dict(self.results))

    def _start(self, plugin_id: str) -> str | None:
        """Start the job for plugin_id; returns an error text when it could not be started."""
        try:
            job_id = self._call("plugin_install_from_repository", plugin_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.exception("Could not start install of %s", plugin_id)
            return f"Could not reach the server: {exc}"
        if not isinstance(job_id, str) or not job_id:
            return "Could not reach the server."
        if job_id.startswith("error:"):
            return job_id.removeprefix("error:").strip() or "Install refused."
        self._job_id = job_id
        return None
