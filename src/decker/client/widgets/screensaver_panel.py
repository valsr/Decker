"""The settings dialog's Device tab: brightness and screensaver controls for the active device."""

import ipaddress
import math
import socket
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from decker.client import config as client_config
from decker.client.context import AppContext
from decker.client.events import ScreensaverSettingsEvent, ScreensaverStateEvent
from decker.common.model import ScreensaverSettings

_APPLY_DEBOUNCE_MS = 500
_PREVIEW_DEBOUNCE_MS = 400
_DEVICE_POLL_MS = 1000
_REMOTE_HINT = "Only available when the client runs on the server's machine"
_NO_DEVICE_HINT = "Connect a device to configure its brightness and screensaver"
_LIVE_HINT = "Changes on this tab are applied immediately; the Apply button does not affect them."
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
    ) -> None:
        super().__init__(parent)
        self._device_id_fn = device_id or (lambda: AppContext.get().active_device_id)
        self._rpc_fn: Callable[[], Any] = rpc or (lambda: AppContext.get().connection_manager)
        self._host_fn = host or client_config.get_server_host
        self._device: str | None = None
        self._base: ScreensaverSettings = _DEFAULTS
        self._active = False
        self._loading = False
        self._dirty: set[str] = set()
        self._fields: dict[str, Any] = {}
        self._build_controls()
        self._build_layout()
        self._apply_timer = self._single_shot(self.flush)
        self._preview_timer = self._single_shot(self.refresh_preview)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.refresh_device)
        self._apply_enabled_states()

    def refresh_device(self) -> None:
        """Pick up a change of the active device and load its settings."""
        device = self._device_id_fn()
        if device == self._device:
            return
        self._device = device
        self._dirty.clear()
        self._apply_timer.stop()
        event = self._rpc_call("screensaver_get", None) if device else None
        if isinstance(event, ScreensaverSettingsEvent):
            self._load(event.settings, force=True)
            self._set_state(bool(event.active), str(event.last_error or ""))
        else:
            self._load(_DEFAULTS, force=True)
            self._set_state(False, "")
        self._apply_enabled_states()
        self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)

    def handle_event(self, event: ScreensaverSettingsEvent | ScreensaverStateEvent) -> None:
        """Resync from a screensaver event for the active device."""
        self.refresh_device()
        if self._device is None or getattr(event, "device_id", None) != self._device:
            return
        if isinstance(event, ScreensaverSettingsEvent):
            self._load(event.settings, force=False)
            self._set_state(bool(event.active), str(event.last_error or ""))
            self._preview_timer.start(_PREVIEW_DEBOUNCE_MS)
        elif isinstance(event, ScreensaverStateEvent):
            self._set_state(bool(event.active), self._last_error_label.text())

    def current_settings(self) -> ScreensaverSettings:
        """The full settings as the controls currently show them."""
        return build_settings(self._control_values(), self._base)

    def flush(self) -> None:
        """Send the current settings to the server now."""
        self._apply_timer.stop()
        rpc = self._rpc_fn()
        if self._device is None or rpc is None:
            return
        settings = self.current_settings()
        ok, error = rpc.screensaver_set(self._device, settings)
        self._dirty.clear()
        if ok:
            self._base = settings
            self._set_error_label.setText("")
        else:
            self._set_error_label.setText(error or "The server rejected these settings")
        self._set_error_label.setVisible(bool(self._set_error_label.text()))

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
            self._preview.setPixmap(pixmap.scaledToWidth(320, Qt.TransformationMode.SmoothTransformation))
        else:
            self._show_preview_text(error or "No preview available")

    def showEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Track the active device while visible."""
        super().showEvent(a0)
        self.refresh_device()
        self._poll_timer.start(_DEVICE_POLL_MS)

    def hideEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Stop tracking the active device while hidden."""
        self._poll_timer.stop()
        super().hideEvent(a0)

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
        self._activate_btn.setText("Wake" if active else "Activate now")
        self._last_error_label.setText(last_error)
        self._last_error_label.setVisible(bool(last_error))

    def _toggle_active(self) -> None:
        rpc = self._rpc_fn()
        if self._device is None or rpc is None:
            return
        if self._active:
            ok = rpc.screensaver_deactivate(self._device)
        else:
            ok = rpc.screensaver_activate(self._device)
        if ok:
            self._set_state(not self._active, "")

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
        self._preview.setMinimumHeight(100)
        self._preview.setWordWrap(True)
        self._activate_btn = QPushButton("Activate now")
        self._activate_btn.clicked.connect(self._toggle_active)
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
        form = QFormLayout()
        form.addRow("Brightness", self._fields["brightness"])
        form.addRow("Start screensaver after", self._fields["timeout_minutes"])
        form.addRow("Screensaver brightness", self._fields["saver_brightness"])
        form.addRow("Content", self._fields["content"])
        form.addRow("Image", self._path_row("image_path", self._image_browse))
        form.addRow("Gallery folder", self._path_row("folder_path", self._folder_browse))
        form.addRow("Scaling", self._fields["scaling"])
        form.addRow("Bezel", self._fields["bezel"])
        form.addRow("Key size", self._fields["key_mm"])
        form.addRow("Key gap", self._fields["gap_mm"])
        form.addRow("Gallery advances", self._fields["gallery_mode"])
        form.addRow("Gallery interval", self._fields["gallery_minutes"])
        self._form_host = QWidget()
        self._form_host.setLayout(form)
        layout = QVBoxLayout(self)
        live_hint = QLabel(_LIVE_HINT)
        live_hint.setWordWrap(True)
        layout.addWidget(live_hint)
        layout.addWidget(self._hint_label)
        layout.addWidget(self._form_host)
        layout.addWidget(self._set_error_label)
        layout.addWidget(self._preview, 1)
        row = QHBoxLayout()
        row.addWidget(self._activate_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self._last_error_label)

    def _path_row(self, name: str, button: QPushButton) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._fields[name], 1)
        box.addWidget(button)
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

    def _apply_enabled_states(self) -> None:
        has_device = self._device is not None and self._rpc_fn() is not None
        remote = not is_loopback_host(self._host_fn())
        self._form_host.setEnabled(has_device)
        self._activate_btn.setEnabled(has_device)
        self._hint_label.setText(_NO_DEVICE_HINT if not has_device else (_REMOTE_HINT if remote else ""))
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
