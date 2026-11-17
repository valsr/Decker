"""Settings control for a profile: a dropdown of the selected key's device profiles, stored as the profile id."""

import json
import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import QComboBox, QWidget

from decker.client.context import AppContext
from decker.client.icon_picker import RpcCaller

_CURRENT = "(current profile)"
_DELETED = "(deleted profile)"
_NO_DEVICE_HINT = "Select a key on a device first"


def _app_device_id() -> str | None:
    return AppContext.get().active_device_id


def _app_rpc() -> RpcCaller | None:
    return AppContext.get().connection_manager


class ProfileEdit(QComboBox):
    """Pick one of the device's profiles; ``value()`` is its id as text, or ``""`` to follow the current profile."""

    value_changed = pyqtSignal()

    def __init__(
        self,
        device_id: Callable[[], str | None] | None = None,
        rpc: Callable[[], RpcCaller | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_id = device_id or _app_device_id
        self._rpc = rpc or _app_rpc
        self._value = ""
        self._profiles: list[tuple[str, str]] = []
        self.activated.connect(self._on_activated)
        self.reload()

    def value(self) -> str:
        """The chosen profile id as text, or an empty string for the current profile."""
        return self._value

    def set_value(self, value: Any) -> None:
        """Show ``value`` (anything but a decimal-id string means the current profile) without emitting."""
        self._value = value if isinstance(value, str) and (value == "" or value.isascii() and value.isdigit()) else ""
        self._rebuild()

    def reload(self) -> None:
        """Re-read the device's profiles from the server."""
        self._profiles = self._fetch_profiles()
        self._rebuild()

    def _fetch_profiles(self) -> list[tuple[str, str]]:
        device_id, rpc = self._device_id(), self._rpc()
        if not device_id or rpc is None:
            return []
        try:
            data = json.loads(rpc.call("profiles_list", device_id) or "null")
            return [(str(p["profile_id"]), str(p["name"])) for p in data["profiles"]]
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("Could not list profiles for %s: %s", device_id, exc)
            return []

    def _rebuild(self) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItem(_CURRENT, "")
        for profile_id, name in self._profiles:
            self.addItem(name, profile_id)
        known = {profile_id for profile_id, _name in self._profiles}
        if self._value and self._profiles and self._value not in known:
            self.addItem(_DELETED, self._value)
            model = self.model()
            item = model.item(self.count() - 1) if isinstance(model, QStandardItemModel) else None
            if item is not None:
                item.setEnabled(False)
        self.setCurrentIndex(max(self.findData(self._value), 0))
        self.setToolTip("" if self._profiles else _NO_DEVICE_HINT)
        self.blockSignals(False)

    def _on_activated(self, index: int) -> None:
        data = self.itemData(index)
        self._value = data if isinstance(data, str) else ""
        self.value_changed.emit()
