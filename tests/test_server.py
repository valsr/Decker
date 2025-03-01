import logging
import time

from assertpy import assert_that

from decker_server.server import Server


class LogCaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


class TestServer:
    def test_server_ping_and_stop(self):
        # Set up log capture
        logger = logging.getLogger()
        original_handlers = logger.handlers[:]
        capture = LogCaptureHandler()
        logger.handlers = [capture]

        server = Server()
        server.start()
        time.sleep(2)
        server.stop()
        # Give time for thread to stop and log stop message.
        server.join(2)

        logger.handlers = original_handlers

        # Assert that there is at least a ping and stop message.
        messages = " ".join(capture.records)
        assert_that(messages).contains("ping")
        assert_that(messages).contains("Stopping server.")
