"""Device view — Stream Deck button grid placeholder for the active device."""

from PyQt6.QtWidgets import QLabel, QVBoxLayout

from decker.client.context import AppContext
from decker.client.views.base import BaseView


class DeviceView(BaseView):
    """Shows the active device. The button grid itself is a placeholder pending hardware wiring."""

    def __init__(self) -> None:
        super().__init__()
        self._title = QLabel()
        self._title.setStyleSheet("color: #a6adc8; font-size: 13px;")
        self._grid_placeholder = QLabel("Button grid placeholder")
        self._grid_placeholder.setStyleSheet("color: #585b70; font-size: 12px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(self._grid_placeholder)
        layout.addStretch()

    def on_activate(self) -> None:
        active_device = AppContext.get().active_device
        self._title.setText(f"Device: {active_device}" if active_device else "No device selected")

    def on_deactivate(self) -> None:
        pass
