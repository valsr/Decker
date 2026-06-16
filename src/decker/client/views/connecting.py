"""Connecting view — shown while the client has no active server connection."""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from decker.client.views.base import BaseView

_TICK_MS = 1_000


class ConnectingView(BaseView):
    """Displays a retry spinner and attempt counter while ConnectionManager reconnects."""

    def __init__(self) -> None:
        super().__init__()
        self._attempts = 0
        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: #1c1c1e; font-size: 14px;")
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.addWidget(self._status_label)
        layout.addStretch()
        self._render()

    def on_activate(self) -> None:
        self._attempts = 0
        self._render()
        self._tick_timer.start(_TICK_MS)

    def on_deactivate(self) -> None:
        self._tick_timer.stop()

    def _on_tick(self) -> None:
        self._attempts += 1
        self._render()

    def _render(self) -> None:
        self._status_label.setText(f"Connecting to server… (attempt {self._attempts})")
