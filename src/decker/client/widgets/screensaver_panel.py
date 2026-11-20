"""The settings dialog's Device tab: a device picker, its details, brightness and screensaver controls."""

import ipaddress
import math
import socket
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from decker.client import config as client_config
from decker.client.context import AppContext
from decker.client.events import ScreensaverSettingsEvent, ScreensaverStateEvent
from decker.common.model import DeviceHardwareInfo, ScreensaverSettings

_APPLY_DEBOUNCE_MS = 500
_PREVIEW_DEBOUNCE_MS = 400
_PREVIEW_WIDTH = 640
_DEVICE_POLL_MS = 1000
_REMOTE_HINT = "Only available when the client runs on the server's machine"
_NO_DEVICE_HINT = "Connect a device to configure its brightness and screensaver"
_FETCH_FAILED_HINT = "Could not load this device's settings from the server; retrying"
_LIVE_HINT = "Changes on this tab are applied immediately; the Apply button does not affect them."
_IMAGE_ROWS = ("image_path",)
_GALLERY_ROWS = ("folder_path", "gallery_mode", "gallery_minutes")
_PICTURE_ROWS = ("scaling", "bezel", "key_mm", "gap_mm")
_CONTENT = ("none", "image", "gallery")
_SCALING = ("center", "stretch")
_GALLERY_MODE = ("activation", "interval")
_IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.svg)"
_DEFAULTS = ScreensaverSettings()


class ScreensaverRpc(Protocol):
    """The ConnectionManager methods the panel uses."""

    def screensaver_get(self, device_id: str) -> ScreensaverSettingsEvent | None:
        """Fetch settings and state."""

    def screensaver_set(self, device_id: str, settings: ScreensaverSettings) -> tuple[bool, str]:
        """Save settings."""

    def screensaver_activate(self, device_id: str) -> bool:
        """Activate the screensaver."""

    def screensaver_deactivate(self, device_id: str) -> bool:
        """Wake the device."""

    def screensaver_preview(self, device_id: str, settings: ScreensaverSettings) -> tuple[bytes | None, str]:
        """Render a draft."""


def is_loopback_host(host: str) -> bool:
    """Whether every address the host resolves to is loopback; unresolvable hosts are remote."""
    name = host.strip().strip("[]")
    if not name:
        return False
    try:
        if name.lower() == "localhost":
            return True
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(name, None)
    except (OSError, UnicodeError):
        return False
    addresses = [str(info[4][0]).split("%", 1)[0] for info in infos]
    try:
        return bool(addresses) and all(ipaddress.ip_address(a).is_loopback for a in addresses)
    except ValueError:
        return False


def _coerce_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, number))


def _coerce_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return max(low, min(high, number))


def _coerce_choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in choices else default


def _coerce_text(value: Any) -> str:
    return value[:1024] if isinstance(value, str) else ""


def _coerce_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def sanitize_settings(settings: Any) -> ScreensaverSettings:
    """Coerce a possibly malformed settings object into valid settings; never raises."""
    d = _DEFAULTS

    def get(name: str) -> Any:
        return getattr(settings, name, None)

    return ScreensaverSettings(
        brightness=_coerce_int(get("brightness"), d.brightness, 1, 100),
        timeout_minutes=_coerce_int(get("timeout_minutes"), d.timeout_minutes, 0, 1440),
        saver_brightness=_coerce_int(get("saver_brightness"), d.saver_brightness, 0, 100),
        content=_coerce_choice(get("content"), _CONTENT, d.content),  # type: ignore[arg-type]
        image_path=_coerce_text(get("image_path")),
        folder_path=_coerce_text(get("folder_path")),
        scaling=_coerce_choice(get("scaling"), _SCALING, d.scaling),  # type: ignore[arg-type]
        bezel=_coerce_bool(get("bezel"), d.bezel),
        key_mm=_coerce_float(get("key_mm"), d.key_mm, 5.0, 60.0),
        gap_mm=_coerce_float(get("gap_mm"), d.gap_mm, 0.0, 30.0),
        gallery_mode=_coerce_choice(get("gallery_mode"), _GALLERY_MODE, d.gallery_mode),  # type: ignore[arg-type]
        gallery_minutes=_coerce_int(get("gallery_minutes"), d.gallery_minutes, 1, 1440),
    )


def build_settings(values: dict[str, Any], base: ScreensaverSettings | None = None) -> ScreensaverSettings:
    """Build full settings from control values keyed by field name, falling back to base for missing keys."""
    return sanitize_settings(replace(base or _DEFAULTS, **values))


def _connected_devices() -> list[DeviceHardwareInfo]:
    manager = AppContext.get().connection_manager
    devices = getattr(manager, "devices", None)
    return list(devices) if isinstance(devices, list) else []


def _device_label(device: DeviceHardwareInfo) -> str:
    return f"{device.type}  ·  {device.serial or device.id}"


def _device_info_html(device: DeviceHardwareInfo) -> str:
    rows = [
        ("Type", device.type),
        ("Serial number", device.serial or "unknown"),
        ("Hardware id", f"{device.vendor_id:04x}:{device.product_id:04x}"),
        ("Firmware", device.firmware or "unknown"),
        ("Keys", str(device.num_keys)),
        ("Device id", str(device.id)),
    ]
    return "<br>".join(f"<b>{label}:</b> {value}" for label, value in rows)


def _separator(title: str) -> QWidget:
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 8, 0, 0)
    label = QLabel(title)
    label.setProperty("role", "title")
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    box.addWidget(label)
    box.addWidget(line, 1)
    return row


def _slider(low: int, high: int) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    return slider


def _combo(items: list[tuple[str, str]]) -> QComboBox:
    combo = QComboBox()
    for label, data in items:
        combo.addItem(label, data)
    return combo


class ScreensaverPanel(QWidget):  # pylint: disable=too-many-instance-attributes
    """Brightness, screensaver content and activation for the active device; edits are applied live."""

    def __init__(
        self,
        device_id: Callable[[], str | None] | None = None,
        rpc: Callable[[], ScreensaverRpc | None] | None = None,
        host: Callable[[], str] | None = None,
        parent: QWidget | None = None,
        devices: Callable[[], list[DeviceHardwareInfo]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_id_fn = device_id or (lambda: AppContext.get().active_device_id)
        self._devices_fn = devices or _connected_devices
        self._picked: str | None = None
        self._listed: list[tuple[str, str]] = []
        self._rpc_fn: Callable[[], Any] = rpc or (lambda: AppContext.get().connection_manager)
        self._host_fn = host or client_config.get_server_host
        self._device: str | None = None
        self._form: QFormLayout = QFormLayout()
        self._base: ScreensaverSettings = _DEFAULTS
        self._active = False
        self._loading = False
        self._fetch_failed = False
        self._loopback_cache: dict[str, bool] = {}
        self._dirty: set[str] = set()
        self._fields: dict[str, Any] = {}
        self._path_hosts: dict[str, QWidget] = {}
        self._build_controls()
        self._build_layout()
        self._apply_timer = self._single_shot(self._flush_quietly)
        self._preview_timer = self._single_shot(self.refresh_preview)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.refresh_device)
        self._apply_enabled_states()

    def refresh_device(self) -> None:
        """Pick up a change of the active device and load its settings."""
        self._sync_device_list()
        device = self._target_device()
        if device == self._device:
            return
        self._device = device
        self._dirty.clear()
        self._apply_timer.stop()
        self._fetch_failed = False
        event = self._rpc_call("screensaver_get", None) if device else None
        if isinstance(event, ScreensaverSettingsEvent):
            self._load(event.settings, force=True)
            self._set_state(bool(event.active), str(event.last_error or ""))
        else:
            self._load(_DEFAULTS, force=True)
            self._set_state(False, "")
            if device:
                # Leave the device unset so the next poll retries; editing defaults would overwrite real settings.
                self._device = None
                self._fetch_failed = True
        self._apply_enabled_states()
        self._schedule_preview()

    def _target_device(self) -> str | None:
        """The device being edited: the one picked in the drop-down, else the client's active device."""
        if self._picked is not None and any(device_id == self._picked for device_id, _label in self._listed):
            return self._picked
        return self._device_id_fn()

    def _sync_device_list(self) -> None:
        devices = [d for d in self._devices_fn() if d.id]
        listed = [(str(d.id), _device_label(d)) for d in devices]
        if listed != self._listed:
            self._listed = listed
            self._device_combo.blockSignals(True)
            self._device_combo.clear()
            for device_id, label in listed:
                self._device_combo.addItem(label, device_id)
            self._device_combo.blockSignals(False)
        self._device_combo.setVisible(bool(listed))
        self._device_caption.setVisible(bool(listed))
        shown = self._target_device()
        index = self._device_combo.findData(shown)
        if index >= 0 and index != self._device_combo.currentIndex():
            self._device_combo.blockSignals(True)
            self._device_combo.setCurrentIndex(index)
            self._device_combo.blockSignals(False)
        info = next((d for d in devices if d.id == shown), None)
        self._info_label.setText(_device_info_html(info) if info is not None else "")
        self._info_label.setVisible(info is not None)

    def _on_device_picked(self) -> None:
        self._picked = self._device_combo.currentData()
        self.refresh_device()

    def handle_event(self, event: ScreensaverSettingsEvent | ScreensaverStateEvent) -> None:
        """Resync from a screensaver event for the active device."""
        self.refresh_device()
        if self._device is None or getattr(event, "device_id", None) != self._device:
            return
        if isinstance(event, ScreensaverSettingsEvent):
            changed = sanitize_settings(event.settings) != self._base
            self._load(event.settings, force=False)
            self._set_state(bool(event.active), str(event.last_error or ""))
            if changed:
                self._schedule_preview()
        elif isinstance(event, ScreensaverStateEvent):
            self._set_state(bool(event.active), self._last_error_label.text())

    def current_settings(self) -> ScreensaverSettings:
        """The full settings as the controls currently show them."""
        return build_settings(self._control_values(), self._base)

    def flush(self) -> bool:
        """Send the current settings to the server now; False when the server rejected them."""
        self._apply_timer.stop()
        rpc = self._rpc_fn()
        if self._device is None or rpc is None:
            return True
        settings = self.current_settings()
        ok, error = rpc.screensaver_set(self._device, settings)
        self._dirty.clear()
        if ok:
            self._base = settings
            self._set_error_label.setText("")
        else:
            self._set_error_label.setText(error or "The server rejected these settings")
        self._set_error_label.setVisible(bool(self._set_error_label.text()))
        return ok

    def refresh_preview(self) -> None:
        """Render the draft settings into the preview pane."""
        self._preview_timer.stop()
        rpc = self._rpc_fn()
        if self._device is None or rpc is None:
            self._show_preview_text("")
            return
        data, error = rpc.screensaver_preview(self._device, self.current_settings())
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self._preview.setText("")
            self._preview.setPixmap(pixmap.scaledToWidth(_PREVIEW_WIDTH, Qt.TransformationMode.SmoothTransformation))
        else:
            self._show_preview_text(error or "No preview available")

    def showEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Track the active device while visible."""
        super().showEvent(a0)
        self.refresh_device()
        self._poll_timer.start(_DEVICE_POLL_MS)
        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)

    def hideEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Stop tracking the active device while hidden."""
        self._poll_timer.stop()
        super().hideEvent(a0)

    def _flush_quietly(self) -> None:
        self.flush()

    def _schedule_preview(self) -> None:
        if self.isVisible() and not self._preview_timer.isActive():
            self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)

    def _is_remote(self) -> bool:
        host = self._host_fn()
        if host not in self._loopback_cache:
            self._loopback_cache[host] = is_loopback_host(host)
        return not self._loopback_cache[host]

    def _single_shot(self, slot: Callable[[], None]) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(slot)
        return timer

    def _rpc_call(self, method: str, default: Any) -> Any:
        rpc = self._rpc_fn()
        if rpc is None or self._device is None:
            return default
        try:
            return getattr(rpc, method)(self._device)
        except Exception:  # pylint: disable=broad-exception-caught
            return default

    def _show_preview_text(self, text: str) -> None:
        self._preview.setPixmap(QPixmap())
        self._preview.setText(text)

    def _set_state(self, active: bool, last_error: str) -> None:
        self._active = active
        self._last_error_label.setText(last_error)
        self._last_error_label.setVisible(bool(last_error))

    def _build_controls(self) -> None:
        f = self._fields
        f["brightness"] = _slider(1, 100)
        f["timeout_minutes"] = self._spin(0, 1440, " min")
        f["timeout_minutes"].setSpecialValueText("0 = never")
        f["saver_brightness"] = _slider(0, 100)
        f["content"] = _combo([("None", "none"), ("Image", "image"), ("Gallery", "gallery")])
        f["image_path"] = QLineEdit()
        f["folder_path"] = QLineEdit()
        f["scaling"] = _combo([("Center", "center"), ("Stretch", "stretch")])
        f["bezel"] = QCheckBox("Hide the image behind the gaps between keys")
        f["key_mm"] = self._dspin(5.0, 60.0, " mm")
        f["gap_mm"] = self._dspin(0.0, 30.0, " mm")
        f["gallery_mode"] = _combo([("Each activation", "activation"), ("Every N minutes", "interval")])
        f["gallery_minutes"] = self._spin(1, 1440, " min")
        for widget in f.values():
            self._connect_edit(widget)
        self._image_browse = QPushButton("Browse…")
        self._image_browse.clicked.connect(lambda: self._browse("image_path", folder=False))
        self._folder_browse = QPushButton("Browse…")
        self._folder_browse.clicked.connect(lambda: self._browse("folder_path", folder=True))
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(200)
        self._preview.setWordWrap(True)
        self._device_combo = QComboBox()
        self._device_combo.currentIndexChanged.connect(lambda _i: self._on_device_picked())
        self._device_caption = QLabel("Device:")
        self._info_label = QLabel()
        self._info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._info_label.setProperty("role", "muted")
        self._content_buttons = QButtonGroup(self)
        self._content_buttons.setExclusive(True)
        self._set_error_label = self._label(role="error")
        self._last_error_label = self._label(role="error")
        self._hint_label = self._label()

    def _label(self, role: str = "") -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setVisible(False)
        if role:
            label.setProperty("role", role)
        return label

    def _spin(self, low: int, high: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSuffix(suffix)
        return spin

    def _dspin(self, low: float, high: float, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(1)
        spin.setSuffix(suffix)
        return spin

    def _connect_edit(self, widget: QWidget) -> None:
        name = next(k for k, w in self._fields.items() if w is widget)
        if isinstance(widget, (QSlider, QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(lambda _v, n=name: self._edited(n))
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(lambda _i, n=name: self._edited(n))
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(lambda _c, n=name: self._edited(n))
        elif isinstance(widget, QLineEdit):
            widget.textEdited.connect(lambda _t, n=name: self._edited(n))

    def _build_layout(self) -> None:
        form = self._form
        form.addRow("Brightness", self._fields["brightness"])
        form.addRow(_separator("Screensaver"))
        form.addRow("Start after", self._fields["timeout_minutes"])
        form.addRow("Brightness", self._fields["saver_brightness"])
        form.addRow(self._content_selector())
        form.addRow("Image", self._path_row("image_path", self._image_browse))
        form.addRow("Gallery folder", self._path_row("folder_path", self._folder_browse))
        form.addRow("Scaling", self._fields["scaling"])
        form.addRow("Bezel", self._fields["bezel"])
        form.addRow("Key size", self._fields["key_mm"])
        form.addRow("Key gap", self._fields["gap_mm"])
        form.addRow("Gallery advances", self._fields["gallery_mode"])
        form.addRow("Gallery interval", self._fields["gallery_minutes"])
        form.addRow(self._preview)
        self._form_host = QWidget()
        self._form_host.setLayout(form)
        content = QWidget()
        layout = QVBoxLayout(content)
        picker = QHBoxLayout()
        picker.addWidget(self._device_caption)
        picker.addWidget(self._device_combo, 1)
        layout.addLayout(picker)
        layout.addWidget(self._info_label)
        live_hint = QLabel(_LIVE_HINT)
        live_hint.setWordWrap(True)
        layout.addWidget(live_hint)
        layout.addWidget(self._hint_label)
        layout.addWidget(self._form_host)
        layout.addWidget(self._set_error_label)
        layout.addWidget(self._last_error_label)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._sync_content_buttons()

    def _content_selector(self) -> QWidget:
        """A NONE | IMAGE | GALLERY segmented control backed by the (hidden) content combo box."""
        combo = self._fields["content"]
        assert isinstance(combo, QComboBox)
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        for index in range(combo.count()):
            button = QPushButton(combo.itemText(index).upper())
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, i=index: combo.setCurrentIndex(i))
            self._content_buttons.addButton(button, index)
            box.addWidget(button)
        combo.currentIndexChanged.connect(self._sync_content_buttons)
        return row

    def _sync_content_buttons(self, _index: int = 0) -> None:
        combo = self._fields["content"]
        assert isinstance(combo, QComboBox)
        button = self._content_buttons.button(combo.currentIndex())
        if button is not None:
            button.setChecked(True)
        content = combo.currentData()
        rows = {
            **{name: content == "image" for name in _IMAGE_ROWS},
            **{name: content == "gallery" for name in _GALLERY_ROWS},
            **{name: content in ("image", "gallery") for name in _PICTURE_ROWS},
        }
        for name, visible in rows.items():
            widget = self._row_widget(name)
            self._form.setRowVisible(widget, visible)
        self._form.setRowVisible(self._preview, content != "none")

    def _row_widget(self, name: str) -> QWidget:
        return self._path_hosts.get(name) or self._fields[name]

    def _path_row(self, name: str, button: QPushButton) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._fields[name], 1)
        box.addWidget(button)
        self._path_hosts[name] = row
        return row

    def _browse(self, name: str, folder: bool) -> None:
        edit = self._fields[name]
        assert isinstance(edit, QLineEdit)
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Gallery folder", edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Screensaver image", edit.text(), _IMAGE_FILTER)
        if path:
            edit.setText(path)
            self._edited(name)

    def _edited(self, name: str) -> None:
        self._apply_enabled_states()
        if self._loading:
            return
        self._dirty.add(name)
        self._apply_timer.start(_APPLY_DEBOUNCE_MS)
        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)

    def _control_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, widget in self._fields.items():
            if isinstance(widget, (QSlider, QSpinBox, QDoubleSpinBox)):
                values[name] = widget.value()
            elif isinstance(widget, QComboBox):
                values[name] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                values[name] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                values[name] = widget.text()
        return values

    def _load(self, settings: Any, force: bool) -> None:
        clean = sanitize_settings(settings)
        self._base = clean
        self._loading = True
        try:
            for name, widget in self._fields.items():
                if not force and (name in self._dirty or widget.hasFocus()):
                    continue
                self._set_control(widget, getattr(clean, name))
        finally:
            self._loading = False
        self._apply_enabled_states()

    def _set_control(self, widget: QWidget, value: Any) -> None:
        if isinstance(widget, (QSlider, QSpinBox, QDoubleSpinBox)):
            widget.setValue(value)
        elif isinstance(widget, QComboBox):
            widget.setCurrentIndex(max(0, widget.findData(value)))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))

    def _hint_text(self, has_device: bool, remote: bool) -> str:
        if self._fetch_failed:
            return _FETCH_FAILED_HINT
        if not has_device:
            return _NO_DEVICE_HINT
        return _REMOTE_HINT if remote else ""

    def _apply_enabled_states(self) -> None:
        has_device = self._device is not None and self._rpc_fn() is not None
        remote = self._is_remote()
        self._form_host.setEnabled(has_device)
        self._hint_label.setText(self._hint_text(has_device, remote))
        self._hint_label.setVisible(bool(self._hint_label.text()))
        paths_ok = not remote
        for name, button in (("image_path", self._image_browse), ("folder_path", self._folder_browse)):
            self._fields[name].setEnabled(paths_ok)
            button.setEnabled(paths_ok)
            self._fields[name].setToolTip("" if paths_ok else _REMOTE_HINT)
        bezel = self._fields["bezel"]
        assert isinstance(bezel, QCheckBox)
        self._fields["key_mm"].setEnabled(bezel.isChecked())
        self._fields["gap_mm"].setEnabled(bezel.isChecked())
        mode = self._fields["gallery_mode"]
        assert isinstance(mode, QComboBox)
        self._fields["gallery_minutes"].setEnabled(mode.currentData() == "interval")
