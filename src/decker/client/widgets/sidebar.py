"""Collapsible sidebar: searchable, draggable plugin action list."""

import json

from PyQt6.QtCore import QByteArray, QMimeData, Qt
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

_MIME_TYPE = "application/x-decker-action"


class _DraggableActionList(QListWidget):
    """QListWidget that starts a custom MIME drag for plugin actions."""

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        item = self.currentItem()
        if item is None:
            return
        data: dict[str, str] = item.data(Qt.ItemDataRole.UserRole) or {}
        mime = QMimeData()
        mime.setData(_MIME_TYPE, QByteArray(json.dumps(data).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class SidebarWidget(QFrame):
    """Search-filterable plugin action list filling the whole sidebar."""

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[dict[str, str]] = []

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search actions...")
        self._search.textChanged.connect(self._apply_filter)

        self._action_list = _DraggableActionList()
        self._action_list.setDragEnabled(True)
        self._action_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._action_list, 1)

    def set_actions(self, actions: list[dict[str, str]]) -> None:
        """Replace the full action list and reapply the current search filter."""
        self._actions = actions
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        self._action_list.clear()
        needle = text.strip().lower()
        for action in self._actions:
            name = action.get("action_name", "")
            if needle and needle not in name.lower():
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, action)
            self._action_list.addItem(item)
