"""Device view — Stream Deck button grid placeholder for the active device."""

from PyQt6.QtWidgets import QLabel, QVBoxLayout

from decker.client.context import AppContext
from decker.client.icon_picker import IconPickerWidget
from decker.client.views.base import BaseView
from decker.common.model import DeviceHardwareInfo


class DeviceView(BaseView):
    """Shows the active device. The button grid itself is a placeholder pending hardware wiring.

    The icon picker below it is wired up generically for now — there is no per-key
    selection UI yet, since key/profile assignment doesn't exist. Picking an icon just
    reports the resolved path via the status label until that lands.
    """

    def __init__(self) -> None:
        super().__init__()
        self._title = QLabel()
        self._title.setProperty("role", "title")
        self._info = QLabel()
        self._info.setProperty("role", "subtitle")
        self._grid_placeholder = QLabel("Button grid placeholder")
        self._grid_placeholder.setProperty("role", "muted")
        self._icon_picker = IconPickerWidget()
        self._icon_picker.icon_selected.connect(self._on_icon_selected)
        self._icon_picker.pack_icon_selected.connect(self._on_pack_icon_selected)
        self._icon_status = QLabel()
        self._icon_status.setProperty("role", "success")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)
        layout.addWidget(self._title)
        layout.addWidget(self._info)
        layout.addWidget(self._grid_placeholder)
        layout.addWidget(self._icon_picker)
        layout.addWidget(self._icon_status)
        layout.addStretch()

    def on_activate(self) -> None:
        device = AppContext.get().active_device
        self._icon_picker.connection_manager = AppContext.get().connection_manager
        self._title.setText(_device_title(device))
        self._info.setText(_device_info(device))

    def on_deactivate(self) -> None:
        pass

    def _on_icon_selected(self, path: str) -> None:
        self._icon_status.setText(f"Selected: {path}")

    def _on_pack_icon_selected(self, pack_id: str, icon_name: str) -> None:
        self._icon_status.setText(f"Selected: {pack_id} / {icon_name}")


def _device_title(device: DeviceHardwareInfo | None) -> str:
    if device is None:
        return "No device selected"
    return device.type or "Stream Deck"


def _device_info(device: DeviceHardwareInfo | None) -> str:
    if device is None:
        return ""
    parts: list[str] = []
    if device.serial:
        parts.append(f"Serial: {device.serial}")
    if device.id:
        parts.append(f"ID: {device.id}")
    if device.path:
        parts.append(f"Path: {device.path}")
    if device.firmware:
        parts.append(f"Firmware: {device.firmware}")
    key_cols = len({k.col for k in device.keys})
    key_rows = len({k.row for k in device.keys})
    if key_rows and key_cols:
        parts.append(f"Keys: {device.num_keys} ({key_rows}×{key_cols})")
    elif device.num_keys:
        parts.append(f"Keys: {device.num_keys}")
    if device.vendor_id or device.product_id:
        parts.append(f"USB: {device.vendor_id:#06x}:{device.product_id:#06x}")
    return "  ·  ".join(parts)
