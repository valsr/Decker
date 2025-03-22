"""Command server operations."""

import logging
import os
import subprocess
import sys
from time import sleep

from decker_server import hardware
from decker_server.error import DeviceNotFoundError


def start_server(device_id: str):
    """Start server for device."""
    logging.info("Starting server for device: %s", device_id)

    devices = hardware.list_devices()
    device = next((d for d in devices if d.get_id() == device_id), None)
    if not device:
        raise DeviceNotFoundError(device_id, devices)

    # Get the current Python executable
    python_executable = sys.executable
    logging.debug("Python executable: %s", python_executable)

    # Start the server as a detached subprocess
    child = subprocess.Popen(
        [python_executable, "-m", "decker_server.server", device_id],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
    )
    logging.debug("Child PID: %s", child.pid)
    logging.info("Server started for device: %s", device_id)


def server_status(device_id: list[str]):
    """Check the status of the server for the device(s)."""
    logging.info("Checking server status for device(s): %s", ",".join(device_id))


def all_servers_status():
    """Check the status of all running servers."""
    logging.info("Checking all running servers status")
