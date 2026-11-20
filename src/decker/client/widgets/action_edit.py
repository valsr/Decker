"""Settings control for an action: a dropdown of the actions the server's plugins provide, stored as the action id."""

import json
import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import QComboBox, QWidget

from decker.client.context import AppContext
from decker.client.icon_picker import RpcCaller

_NONE = "(choose an action)"
_MISSING = "(missing action)"
_OFFLINE_HINT = "Connect to the server to list its actions"


def _app_rpc() -> RpcCaller | None:
    return AppContext.get().connection_manager


def fetch_actions(rpc: RpcCaller | None) -> list[dict[str, Any]] | None:
    """The server's actions (None when they cannot be listed)."""
    if rpc is None:
        return None
    try:
        data = json.loads(rpc.call("plugins_actions_list") or "null")
    except Exception as exc:  # pylint: disable=broad-except
        logging.warning("Could not list actions: %s", exc)
        return None
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else None


class ActionEdit(QComboBox):
    """Pick one of the available actions; ``value()`` is its id, or ``""`` for none."""

    value_changed = pyqtSignal()

    def __init__(self, rpc: Callable[[], RpcCaller | None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rpc = rpc or _app_rpc
        self._value = ""
        self._actions: list[dict[str, Any]] = []
        self._online = False
        self.activated.connect(self._on_activated)
        self.reload()

    def value(self) -> str:
        """The chosen action id, or an empty string."""
        return self._value

    def set_value(self, value: Any) -> None:
        """Show ``value`` (anything but a string means none) without emitting ``value_changed``."""
        self._value = value if isinstance(value, str) else ""
        self._rebuild()

    def reload(self) -> None:
        """Re-read the actions from the server."""
        listed = fetch_actions(self._rpc())
        self._online = listed is not None
        self._actions = listed or []
        self._rebuild()

    def _rebuild(self) -> None:
        self.blockSignals(True)
        self.clear()
        self.addItem(_NONE, "")
        for action in sorted(self._actions, key=lambda a: (str(a.get("plugin_name")), str(a.get("action_name")))):
            self.addItem(f"{action.get('plugin_name')}: {action.get('action_name')}", str(action["action_uuid"]))
        known = {str(a["action_uuid"]) for a in self._actions}
        if self._value and self._online and self._value not in known:
            self.addItem(_MISSING, self._value)
            model = self.model()
            item = model.item(self.count() - 1) if isinstance(model, QStandardItemModel) else None
            if item is not None:
                item.setEnabled(False)
        self.setCurrentIndex(max(self.findData(self._value), 0))
        self.setToolTip("" if self._online else _OFFLINE_HINT)
        self.blockSignals(False)

    def _on_activated(self, index: int) -> None:
        data = self.itemData(index)
        self._value = data if isinstance(data, str) else ""
        self.value_changed.emit()
