"""Sequential repository installs/updates: one server job at a time, advanced by finished events."""

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

RESULT_OK = "ok"


Submit = Callable[[Callable[[], Any], Callable[[Any], None]], None]


def _run_inline(work: Callable[[], Any], done: Callable[[Any], None]) -> None:
    try:
        result: Any = work()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        result = exc
    done(result)


class UpdateRunner:
    """Runs `plugin_install_from_repository` for a list of plugin ids, one job after another.

    Qt-free. `submit(work, done)` must run `work` off the UI thread and call `done(result)` on the thread that
    owns the runner (an exception from `work` is passed as the result); the default runs inline. Feed every
    `plugin_install_finished` event to `on_finished`; it may arrive before the start call returns the job id, in
    which case it is held and replayed.
    """

    def __init__(
        self,
        call: Callable[..., Any],
        on_complete: Callable[[dict[str, str]], None] | None = None,
        submit: Submit = _run_inline,
    ) -> None:
        self._call = call
        self._on_complete = on_complete
        self._submit = submit
        self._epoch: int = 0
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

    def reset(self, reason: str = "Interrupted: the connection to the server was lost") -> None:
        """Abandon the run (e.g. after a disconnect), recording the interrupted item and reporting completion."""
        if not self.busy:
            return
        if self._current is not None:
            self.results[self._current] = reason
        self._queue.clear()
        self._epoch += 1
        self._current, self._job_id, self._early = None, None, None
        self._complete()

    def _advance(self) -> None:
        if not self._queue:
            self._complete()
            return
        plugin_id = self._queue.popleft()
        self._current, self._job_id, self._early = plugin_id, None, None
        epoch = self._epoch
        self._submit(
            lambda: self._call("plugin_install_from_repository", plugin_id),
            lambda outcome: self._started(epoch, plugin_id, outcome),
        )

    def _complete(self) -> None:
        if self._on_complete is not None:
            self._on_complete(dict(self.results))

    def _started(self, epoch: int, plugin_id: str, outcome: Any) -> None:
        if epoch != self._epoch or self._current != plugin_id:
            return  # the run was reset while the call was in flight
        error = self._start_error(plugin_id, outcome)
        if error is not None:
            self.results[plugin_id] = error
            self._current = None
            self._advance()
            return
        self._job_id = str(outcome)
        if self._early is not None:
            early_job, ok, message = self._early
            self._early = None
            if early_job == self._job_id:
                self._finish_current(ok, message)
                self._advance()

    @staticmethod
    def _start_error(plugin_id: str, outcome: Any) -> str | None:
        """Return an error text when the job could not be started."""
        if isinstance(outcome, Exception):
            logging.error("Could not start install of %s: %s", plugin_id, outcome)
            return f"Could not reach the server: {outcome}"
        if not isinstance(outcome, str) or not outcome:
            return "Could not reach the server."
        if outcome.startswith("error:"):
            return outcome.removeprefix("error:").strip() or "Install refused."
        return None
