"""Decker client — main window and view navigation."""

import logging
import sys
from typing import Any

import rpyc.utils.factory
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget
from rpyc.core.protocol import Connection

import decker.common.logging
from decker.client.assets import ICON_PATH
from decker.client.view import ConnectView, DeviceView, ViewManager
from decker.common import config


class ClientWindow(QMainWindow):
    """Main application window. Owns the view manager and handles server connection."""

    def __init__(self) -> None:
        super().__init__()
        self._host: str = config.get_as("client.server_host", str)
        self._port: int = config.get_as("client.server_port", int)
        self._conn: Connection | None = None

        stack = QStackedWidget()
        self._manager = ViewManager(stack)
        self._connect_view = ConnectView(self._host, self._port)
        self._device_view = DeviceView()
        self._manager.register("connect", self._connect_view)
        self._manager.register("device", self._device_view)
        self._connect_view.connect_requested.connect(self._try_connect)
        self._device_view.server_lost.connect(self._on_server_lost)
        self._build_ui(stack)

    def show(self) -> None:
        """Show the window, navigate to the connect view, and attempt the initial connection."""
        super().show()
        self._manager.navigate("connect")
        self._try_connect(self._host, self._port)

    def closeEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Stop active timers and close the server connection cleanly."""
        self._manager.hide_current()
        self._disconnect()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ui(self, stack: QStackedWidget) -> None:
        self.setWindowTitle("Decker")
        self.setStyleSheet("background-color: #1e1e2e;")
        self.resize(320, 240)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setCentralWidget(stack)

    def _try_connect(self, host: str, port: int) -> None:
        """Attempt to connect to the server and load the first device on success."""
        self._disconnect()
        try:
            self._conn = rpyc.utils.factory.connect(host, port)
            logging.info("Connected to server at %s:%d", host, port)
            self._host, self._port = host, port
            self._load_device()
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not connect to server: %s", e)
            self._connect_view.show_error(f"Cannot connect to {host}:{port} — {e}")
            self._manager.navigate("connect")

    def _on_server_lost(self, error_msg: str) -> None:
        """Handle a failed heartbeat — disconnect and return to the connect view."""
        self._disconnect()
        self._connect_view.show_error(error_msg)
        self._manager.navigate("connect")

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._conn = None

    def _load_device(self) -> None:
        """Fetch the first device from the server and navigate to the device view."""
        if self._conn is None:
            return
        try:
            devices = list(self._conn.root.devices_list())
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not list devices: %s", e)
            self._connect_view.show_error(f"Connected but could not list devices — {e}")
            self._manager.navigate("connect")
            return

        if not devices:
            self._connect_view.show_error("No Stream Deck devices found. Connect a device and try again.")
            self._manager.navigate("connect")
            return

        device = dict(devices[0])
        if device_id := device.get("id"):
            config.set("client.default_device", str(device_id))

        self._device_view.set_connection(self._conn)
        w, h = self._device_view.set_device(device)
        self._manager.navigate("device")
        self.resize(w, h)


def main() -> None:
    """Client entry point."""
    decker.common.logging.configure(level=logging.WARNING)
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
