import logging
import time

from assertpy import assert_that

from decker_server.logging import LOGGED, PerformanceLogger, configure, debug_once


class TestLogging:
    def test_configure(self):
        # Reset logging
        logger = logging.getLogger()
        logger.handlers.clear()
        configure(logging.DEBUG)
        # Expect three handlers: stream, error file and file handler.
        assert_that(len(logger.handlers)).is_equal_to(3)

    def test_performance_logger(self, monkeypatch):
        messages = []

        def fake_log(level, msg, *args, **kwargs):
            messages.append(msg)

        monkeypatch.setattr(logging, "log", fake_log)
        with PerformanceLogger("Test operation") as pl:
            time.sleep(0.1)
        # Check that some log message was received.
        assert_that(messages).is_not_empty()

    def test_log_once(self, monkeypatch):
        # Clear already logged keys.
        LOGGED.clear()
        output = []

        def fake_log(level, msg, *args, **kwargs):
            output.append(msg)

        monkeypatch.setattr(logging, "log", fake_log)
        # Call twice and expect only one log.
        debug_once("unique_key", "This should log only once.")
        debug_once("unique_key", "This should log only once.")
        assert_that(len(output)).is_equal_to(1)
