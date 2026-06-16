"""Dashboard view — device list and profile management."""

from typing import Any

from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from decker.client.context import AppContext
from decker.client.events import AppEvent, DeviceListUpdatedEvent
from decker.client.views.base import BaseView


class DashboardView(BaseView):
    """Lists known devices and lets the user pick one to manage. Profile management is a placeholder."""

    def __init__(self) -> None:
        super().__init__()
        self._title = QLabel("Devices")
        self._title.setStyleSheet("color: #cdd6f4; font-size: 16px; font-weight: bold;")
        self._list_layout = QVBoxLayout()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addLayout(self._list_layout)
        layout.addStretch()

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def handle_event(self, event: AppEvent) -> None:
        if isinstance(event, DeviceListUpdatedEvent):
            self._render_devices(event.devices)

    def _render_devices(self, devices: list[dict[str, Any]]) -> None:
        while (item := self._list_layout.takeAt(0)) is not None:
            if widget := item.widget():
                widget.deleteLater()

        if not devices:
            self._list_layout.addWidget(QLabel("No Stream Deck devices found."))
            return

        for device in devices:
            serial = str(device.get("serial") or "")
            device_type = str(device.get("type", "Stream Deck"))
            label = f"{device_type}  ·  {serial}"
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, s=serial: self._select_device(s))
            self._list_layout.addWidget(btn)

    def _select_device(self, serial: str) -> None:
        window = AppContext.get().window
        if window is not None:
            window.switch_device(serial)
