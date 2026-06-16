"""Dedicated thread pool for running plugin callbacks in isolation from the server."""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor  # pylint: disable=no-name-in-module
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

_DEFAULT_TIMEOUT_S = 5.0


class PluginExecutor:
    """Runs plugin callbacks on a dedicated pool; a raising or hanging callback never affects the server."""

    def __init__(self, max_workers: int = 4, timeout: float = _DEFAULT_TIMEOUT_S) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="decker-plugin")
        self._timeout = timeout

    def dispatch(self, plugin_uuid: str, callback: Callable[..., Any], *args: Any) -> None:
        """Run callback(*args) on the pool, logging (not raising) on error or timeout."""
        future = self._pool.submit(callback, *args)
        try:
            future.result(timeout=self._timeout)
        except FutureTimeoutError:
            logging.error("Plugin %s callback %s timed out after %.1fs", plugin_uuid, callback, self._timeout)
        except Exception as exc:  # pylint: disable=broad-except
            logging.error("Plugin %s callback %s raised: %s", plugin_uuid, callback, exc)

    def shutdown(self) -> None:
        """Stop accepting new callbacks and wait for in-flight ones to finish."""
        self._pool.shutdown(wait=True)
