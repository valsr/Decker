import logging
import time
from typing import Any

from assertpy import assert_that
from pytest import MonkeyPatch

from decker.common.logging import LOGGED, PerformanceLogger, configure, debug_once


class TestLogging:
    def test_configure(self):
        # Reset logging
        logger = logging.getLogger()
        logger.handlers.clear()
        configure(logging.DEBUG)
        # Expect three handlers: stream and file.
        assert_that(len(logger.handlers)).is_equal_to(2)

    def test_performance_logger(self, monkeypatch: MonkeyPatch):
        messages: list[str] = []

        def fake_log(_level: Any, msg: str, *_args: Any, **_kwargs: Any):
            messages.append(msg)

        monkeypatch.setattr(logging, "log", fake_log)
        with PerformanceLogger("Test operation"):
            time.sleep(0.1)
        # Check that some log message was received.
        assert_that(messages).is_not_empty()

    def test_log_once(self, monkeypatch: MonkeyPatch):
        # Clear already logged keys.
        LOGGED.clear()
        output: list[str] = []

        def fake_log(_level: Any, msg: str, *_args: Any, **_kwargs: Any):
            output.append(msg)

        monkeypatch.setattr(logging, "log", fake_log)
        # Call twice and expect only one log.
        debug_once("unique_key", "This should log only once.")
        debug_once("unique_key", "This should log only once.")
        assert_that(len(output)).is_equal_to(1)
