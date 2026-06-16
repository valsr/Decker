"""Device view — shown when connected, displaying the Stream Deck button grid."""

import logging
from typing import Any

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from rpyc.core.protocol import Connection

from decker.client.view.base import View

_HEARTBEAT_MS = 5_000
_BTN_SIZE = 64
_BTN_GAP = 8
_PAGE_MARGIN = 20

_DEVICE_GRIDS: dict[str, tuple[int, int]] = {
    "Stream Deck Mini": (2, 3),
    "Stream Deck": (3, 5),
    "Stream Deck MK.2": (3, 5),
    "Stream Deck XL": (4, 8),
    "Stream Deck +": (2, 4),
    "Stream Deck Pedal": (1, 3),
}

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


class DeviceView(View):
    """Displays the device button grid and monitors server health via periodic heartbeats."""

    server_lost = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._conn: Connection | None = None
        self._title = QLabel()
        self._title.setStyleSheet("color: #a6adc8; font-size: 13px;")
        self._grid_widget: QWidget | None = None
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._heartbeat_check)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN, _PAGE_MARGIN)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addStretch()
        self._layout = layout

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        self._heartbeat_timer.start(_HEARTBEAT_MS)

    def on_hide(self) -> None:
        self._heartbeat_timer.stop()
        self._conn = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_connection(self, conn: Connection) -> None:
        """Store the RPyC connection used for heartbeat checks."""
        self._conn = conn

    def set_device(self, device: dict[str, Any]) -> tuple[int, int]:
        """Rebuild the button grid for a device. Returns desired (window_w, window_h) in pixels."""
        device_type = str(device.get("type", "Stream Deck"))
        key_count = int(device.get("keys", 6))
        serial = str(device.get("serial") or "")
        self._title.setText(f"{device_type}  ·  {serial}" if serial else device_type)
        rows, cols = _grid_shape(device_type, key_count)
        self._replace_grid(rows, cols)
        grid_w = cols * _BTN_SIZE + (cols - 1) * _BTN_GAP
        grid_h = rows * _BTN_SIZE + (rows - 1) * _BTN_GAP
        return grid_w + 2 * _PAGE_MARGIN, grid_h + 72

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _replace_grid(self, rows: int, cols: int) -> None:
        if self._grid_widget is not None:
            self._layout.removeWidget(self._grid_widget)
            self._grid_widget.deleteLater()
        self._grid_widget = self._make_grid(rows, cols)
        self._layout.insertWidget(1, self._grid_widget)

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
        container.setFixedSize(
            cols * _BTN_SIZE + (cols - 1) * _BTN_GAP,
            rows * _BTN_SIZE + (rows - 1) * _BTN_GAP,
        )
        return container

    def _heartbeat_check(self) -> None:
        if self._conn is None:
            return
        try:
            response = self._conn.root.heartbeat()
            if response.get("status") != "healthy":
                raise ValueError(f"unexpected response: {response!r}")
        except Exception as e:  # pylint: disable=broad-except
            logging.warning("Server heartbeat failed: %s", e)
            self.server_lost.emit(f"Lost connection to server — {e}")
