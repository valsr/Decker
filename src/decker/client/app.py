"""Decker client GUI — connects to the server and provides a control interface."""

# pylint: disable=duplicate-code  # intentionally mirrors connection.py cleanup pattern

import logging
import sys
from typing import Any

import rpyc.utils.factory
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from rpyc.core.protocol import Connection

import decker.common.logging
from decker.common import config

_DEVICE_GRIDS: dict[str, tuple[int, int]] = {
    "Stream Deck Mini": (2, 3),
    "Stream Deck": (3, 5),
    "Stream Deck MK.2": (3, 5),
    "Stream Deck XL": (4, 8),
    "Stream Deck +": (2, 4),
    "Stream Deck Pedal": (1, 3),
}

_BTN_SIZE = 64
_BTN_GAP = 8
_PAGE_MARGIN = 20
_HEARTBEAT_MS = 5_000
_RETRY_MS = 5_000

_GLASS_BTN_STYLE = """
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,70), stop:0.4 rgba(200,200,220,25),
        stop:0.5 rgba(140,140,170,10), stop:1 rgba(30,30,50,120));
    border: 1px solid rgba(180,180,220,140);
    border-radius: 10px;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255,255,255,110), stop:0.4 rgba(220,220,240,45),
        stop:0.5 rgba(180,180,200,20), stop:1 rgba(60,60,90,140));
    border: 1px solid rgba(210,210,255,190);
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(20,20,45,130), stop:1 rgba(255,255,255,50));
}
"""


def _grid_shape(device_type: str, key_count: int) -> tuple[int, int]:
    """Return (rows, cols) for a device type, falling back to factoring key_count."""
    if device_type in _DEVICE_GRIDS:
        return _DEVICE_GRIDS[device_type]
    for rows in range(1, 9):
        if key_count % rows == 0:
            cols = key_count // rows
            if cols >= rows:
                return (rows, cols)
    return (1, key_count)


def _parse_address(text: str, default_port: int) -> tuple[str, int]:
    """Parse 'host' or 'host:port' text into (host, port)."""
    if ":" in text:
        parts = text.rsplit(":", 1)
        try:
            return parts[0].strip(), int(parts[1].strip())
        except ValueError:
            pass
    return text.strip(), default_port


class _ConnectPage(QWidget):
    """Startup page shown when the client cannot reach the server."""

    connect_requested = pyqtSignal(str, int)

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._default_port = port
        self._error_label = QLabel()
        self._error_label.setStyleSheet("color: #f38ba8;")
        self._error_label.setWordWrap(True)
        self._error_label.setVisible(False)
        self._address_input = QLineEdit(f"{host}:{port}")
        self._retry_timer = QTimer(self)
        self._retry_timer.timeout.connect(self._on_retry_tick)
        self.setMinimumWidth(300)
        self._build_ui()

    def show_error(self, message: str) -> None:
        """Display an error message above the connect form."""
        self._error_label.setText(message)
        self._error_label.setVisible(True)

    def clear_error(self) -> None:
        """Hide the current error message."""
        self._error_label.setVisible(False)

    def start_auto_retry(self) -> None:
        """Start retrying the connection every 5 seconds (no-op if already running)."""
        if not self._retry_timer.isActive():
            self._retry_timer.start(_RETRY_MS)

    def stop_auto_retry(self) -> None:
        """Stop the automatic retry loop."""
        self._retry_timer.stop()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(10)

        title = QLabel("Decker")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
        root.addWidget(title)

        root.addWidget(self._error_label)

        addr_label = QLabel("Server address")
        addr_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        root.addWidget(addr_label)

        self._address_input.setStyleSheet(
            "background: #313244; color: #cdd6f4; border: 1px solid #585b70;"
            " border-radius: 6px; padding: 6px 8px; font-size: 13px;"
        )
        self._address_input.setPlaceholderText("localhost:18861")
        root.addWidget(self._address_input)

        btn = QPushButton("Connect")
        btn.setStyleSheet(
            "QPushButton { background: #89b4fa; color: #1e1e2e; border-radius: 6px;"
            " padding: 8px; font-weight: bold; font-size: 13px; border: none; }"
            " QPushButton:hover { background: #b4d0fa; }"
            " QPushButton:pressed { background: #6090da; }"
        )
        btn.clicked.connect(self._on_connect_clicked)
        root.addWidget(btn)
        root.addStretch()

    def _on_connect_clicked(self) -> None:
        host, port = _parse_address(self._address_input.text(), self._default_port)
        self.connect_requested.emit(host, port)

    def _on_retry_tick(self) -> None:
        host, port = _parse_address(self._address_input.text(), self._default_port)
        self.connect_requested.emit(host, port)


class _DevicePage(QWidget):
    """Page shown when connected, displaying the device's button grid."""

    def __init__(self) -> None:
        super().__init__()
        self._title = QLabel()
        self._title.setStyleSheet("color: #a6adc8; font-size: 13px;")
        self._grid_widget: QWidget | None = None
        self._inner_layout = QVBoxLayout(self)
        self._inner_layout.setContentsMargins(_PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN)
        self._inner_layout.setSpacing(10)
        self._inner_layout.addWidget(self._title)
        self._inner_layout.addStretch()

    def set_device(self, device: dict[str, Any]) -> tuple[int, int]:
        """Rebuild the button grid for the given device. Returns (grid_w, grid_h) in pixels."""
        device_type = str(device.get("type", "Stream Deck"))
        key_count = int(device.get("keys", 6))
        serial = str(device.get("serial") or "")
        subtitle = f"{device_type}  ·  {serial}" if serial else device_type
        self._title.setText(subtitle)
        rows, cols = _grid_shape(device_type, key_count)
        self._replace_grid(rows, cols)
        return cols * _BTN_SIZE + (cols - 1) * _BTN_GAP, rows * _BTN_SIZE + (rows - 1) * _BTN_GAP

    def clear(self) -> None:
        """Remove the current device grid and title."""
        self._title.setText("")
        if self._grid_widget is not None:
            self._inner_layout.removeWidget(self._grid_widget)
            self._grid_widget.deleteLater()
            self._grid_widget = None

    def _replace_grid(self, rows: int, cols: int) -> None:
        if self._grid_widget is not None:
            self._inner_layout.removeWidget(self._grid_widget)
            self._grid_widget.deleteLater()
        self._grid_widget = self._make_grid(rows, cols)
        self._inner_layout.insertWidget(1, self._grid_widget)

    def _make_grid(self, rows: int, cols: int) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(_BTN_GAP)
        for r in range(rows):
            for c in range(cols):
                btn = QPushButton()
                btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
                btn.setStyleSheet(_GLASS_BTN_STYLE)
                grid.addWidget(btn, r, c)
        grid_w = cols * _BTN_SIZE + (cols - 1) * _BTN_GAP
        grid_h = rows * _BTN_SIZE + (rows - 1) * _BTN_GAP
        container.setFixedSize(grid_w, grid_h)
        return container


class ClientWindow(QMainWindow):
    """Main application window: shows a connect form or the device button grid."""

    def __init__(self) -> None:
        super().__init__()
        self._host: str = config.get_as("client.server_host", str)
        self._port: int = config.get_as("client.server_port", int)
        self._conn: Connection | None = None
        self._connect_page = _ConnectPage(self._host, self._port)
        self._device_page = _DevicePage()
        self._pages = QStackedWidget()
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._heartbeat_check)
        self._build_ui()

    def show(self) -> None:
        """Show the window and attempt the first connection."""
        super().show()
        self._try_connect(self._host, self._port)

    def closeEvent(self, event: Any) -> None:  # pylint: disable=invalid-name
        """Stop timers and disconnect cleanly before closing."""
        self._heartbeat_timer.stop()
        self._connect_page.stop_auto_retry()
        self._disconnect()
        super().closeEvent(event)

    def _build_ui(self) -> None:
        self.setWindowTitle("Decker")
        self.setStyleSheet("background-color: #1e1e2e;")
        self.resize(320, 240)
        self._pages.addWidget(self._connect_page)  # index 0: connect form
        self._pages.addWidget(self._device_page)  # index 1: device grid
        self.setCentralWidget(self._pages)
        self._connect_page.connect_requested.connect(self._try_connect)

    def _try_connect(self, host: str, port: int) -> None:
        """Connect to the server and load the first device on success."""
        self._disconnect()
        self._connect_page.clear_error()
        try:
            self._conn = rpyc.utils.factory.connect(host, port)
            logging.info("Connected to server at %s:%d", host, port)
            self._host, self._port = host, port
            self._load_device()
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not connect to server: %s", e)
            self._go_connect_page(f"Cannot connect to {host}:{port} — {e}")

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._conn = None

    def _heartbeat_check(self) -> None:
        """Periodic health check; returns to the connect page if the server is unreachable."""
        if self._conn is None:
            return
        try:
            response = self._conn.root.heartbeat()
            if response.get("status") != "healthy":
                raise ValueError(f"unexpected response: {response!r}")
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Server heartbeat failed: %s", e)
            self._go_connect_page(f"Lost connection to server — {e}")

    def _go_connect_page(self, error_msg: str = "") -> None:
        """Switch to the connect page, show an error if given, and start auto-retry."""
        self._heartbeat_timer.stop()
        self._disconnect()
        if error_msg:
            self._connect_page.show_error(error_msg)
        self._pages.setCurrentIndex(0)
        self._connect_page.start_auto_retry()

    def _load_device(self) -> None:
        """Fetch the device list and switch to the device grid on success."""
        if self._conn is None:
            return
        try:
            devices = list(self._conn.root.devices_list())
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Could not list devices: %s", e)
            self._go_connect_page(f"Connected but could not list devices — {e}")
            return

        if not devices:
            self._go_connect_page("No Stream Deck devices found. Connect a device and try again.")
            return

        self._go_device_page(dict(devices[0]))

    def _go_device_page(self, device: dict[str, Any]) -> None:
        """Persist the default device, build the grid, switch page, and start heartbeat."""
        device_id = device.get("id")
        if device_id:
            config.set("client.default_device", str(device_id))
        self._connect_page.stop_auto_retry()
        grid_w, grid_h = self._device_page.set_device(device)
        self._pages.setCurrentIndex(1)
        self.resize(grid_w + 2 * _PAGE_MARGIN, grid_h + 72)
        self._heartbeat_timer.start(_HEARTBEAT_MS)


def main() -> None:
    """Client entry point."""
    decker.common.logging.configure(level=logging.WARNING)
    app = QApplication(sys.argv)
    window = ClientWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
