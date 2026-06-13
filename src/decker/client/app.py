"""Decker client GUI — connects to the server and provides a control interface."""

import logging
import sys
from typing import Any

import rpyc.utils.factory
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from rpyc.core.protocol import Connection

import decker.common.logging
from decker.common import config


class ClientWindow(QMainWindow):
    """Main window for the Decker client."""

    _POLL_INTERVAL_MS = 3000

    def __init__(self) -> None:
        super().__init__()
        self._host: str = config.get_as("client.server_host", str)
        self._port: int = config.get_as("client.server_port", int)
        self._conn: Connection | None = None

        self._status_label = QLabel("Disconnected")
        self._app_label = QLabel("—")
        self._btn_start = QPushButton("Start")
        self._btn_stop = QPushButton("Stop")

        self._poll_timer = QTimer(self)
        self._reconnect_timer = QTimer(self)

        self._build_ui()
        self._setup_timers()

    def show(self) -> None:
        """Show the window and initiate the first connection attempt."""
        super().show()
        self._connect()

    def closeEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Disconnect cleanly before closing."""
        self._disconnect()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Decker")
        self.setFixedSize(320, 160)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(6)

        server_row = QHBoxLayout()
        server_row.addWidget(QLabel("<b>Server</b>"))
        addr = QLabel(f"{self._host}:{self._port}")
        addr.setStyleSheet("color: gray;")
        server_row.addWidget(addr)
        server_row.addStretch()
        root.addLayout(server_row)

        root.addWidget(self._make_separator())

        grid_widget = QWidget()
        grid = QVBoxLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)

        conn_row = QHBoxLayout()
        conn_row.addWidget(QLabel("Connection:"))
        conn_row.addWidget(self._status_label)
        conn_row.addStretch()
        grid.addLayout(conn_row)

        app_row = QHBoxLayout()
        app_row.addWidget(QLabel("Application:"))
        app_row.addWidget(self._app_label)
        app_row.addStretch()
        grid.addLayout(app_row)

        root.addWidget(grid_widget)
        root.addWidget(self._make_separator())

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)
        reconnect_btn = QPushButton("Reconnect")
        btn_row.addWidget(reconnect_btn)
        root.addLayout(btn_row)

        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        reconnect_btn.clicked.connect(self._connect)

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def _setup_timers(self) -> None:
        self._poll_timer.timeout.connect(self._poll_status)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._connect)

    # ------------------------------------------------------------------
    # Server communication
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._disconnect()
        try:
            self._conn = rpyc.utils.factory.connect(self._host, self._port)
            self._status_label.setText("Connected")
            logging.info("Connected to server at %s:%d", self._host, self._port)
            self._poll_timer.start(self._POLL_INTERVAL_MS)
            self._poll_status()
        except Exception as e:
            self._status_label.setText("Disconnected")
            logging.warning("Could not connect to server: %s", e)
            self._reconnect_timer.start(self._POLL_INTERVAL_MS)

    def _disconnect(self) -> None:
        self._poll_timer.stop()
        self._reconnect_timer.stop()
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._status_label.setText("Disconnected")
        self._app_label.setText("—")

    def _poll_status(self) -> None:
        if self._conn is None:
            return
        try:
            status: dict[str, Any] = self._conn.root.status()
            running = status.get("application_running", False)
            self._app_label.setText("Running" if running else "Stopped")
        except Exception as e:
            logging.warning("Lost connection to server: %s", e)
            self._disconnect()
            self._reconnect_timer.start(self._POLL_INTERVAL_MS)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        self._rpc("start")

    def _on_stop(self) -> None:
        self._rpc("stop")

    def _rpc(self, method: str) -> Any:
        if self._conn is None:
            self._status_label.setText("Not connected")
            return None
        try:
            return getattr(self._conn.root, method)()
        except Exception as e:
            logging.error("RPC %s failed: %s", method, e)
            self._disconnect()
            self._reconnect_timer.start(self._POLL_INTERVAL_MS)
            return None


def main() -> None:
    """Client entry point."""
    decker.common.logging.configure(level=logging.WARNING)
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
