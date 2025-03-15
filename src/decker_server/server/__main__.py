"""Script that starts Decker server instance."""

import logging
import os

import decker_server.logging
import decker_server.config

if __name__ == "__main__":
    from time import sleep

    # configure logging
    # TODO Use device id
    log_dir = str(decker_server.config.get("log_dir") or "")
    decker_server.logging.configure(level=logging.DEBUG, log_dir=log_dir, server_id=os.getpid())

    logging.basicConfig(level=logging.DEBUG)
    logging.debug("Starting server")
    sleep(120)
    logging.debug("Stopping server")
