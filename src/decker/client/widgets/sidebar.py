"""Collapsible sidebar: searchable grid of plugin actions (icon + name), dragged onto keys by their icon."""

import json
from typing import Any

from PyQt6.QtCore import QByteArray, QMimeData, QPoint, QSize, Qt
from PyQt6.QtGui import QDrag, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from decker.client.action_icons import action_pixmap

_MIME_TYPE = "application/x-decker-action"
ICON_SIZE = 48
DRAG_ICON_SIZE = 56
_TILE_SIZE = QSize(96, 104)  # room for a two-line name under the icon
_ICON_SOURCE_SIZE = ICON_SIZE * 2  # rendered at 2x so icons stay sharp on high-DPI screens
_DRAG_FIELDS = ("plugin_uuid", "plugin_name", "action_uuid", "action_name")


class _DraggableActionList(QListWidget):
    """Icon-mode QListWidget whose drags carry the action as custom MIME data and show its icon."""

    def build_drag(self, item: QListWidgetItem) -> QDrag:
        """Create the drag for item: the action (without its icon bytes) as MIME data, its icon as the image."""
        action: dict[str, Any] = item.data(Qt.ItemDataRole.UserRole) or {}
        payload = {field: action[field] for field in _DRAG_FIELDS if field in action}
        mime = QMimeData()
        mime.setData(_MIME_TYPE, QByteArray(json.dumps(payload).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = action_pixmap(action, DRAG_ICON_SIZE)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        return drag

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # pylint: disable=invalid-name,unused-argument
        """Drag the current action by its icon."""
        item = self.currentItem()
        if item is not None:
            self.build_drag(item).exec(Qt.DropAction.CopyAction)


class SidebarWidget(QFrame):
    """Search-filterable grid of plugin action tiles (icon above name) filling the whole sidebar."""

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[dict[str, Any]] = []
        self._icons: dict[tuple[str, str], QIcon] = {}

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search actions...")
        self._search.textChanged.connect(self._apply_filter)

        self._action_list = _DraggableActionList()
        self._action_list.setObjectName("action-list")
        self._action_list.setViewMode(QListView.ViewMode.IconMode)
        self._action_list.setFlow(QListView.Flow.LeftToRight)
        self._action_list.setWrapping(True)
        self._action_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._action_list.setMovement(QListView.Movement.Static)
        self._action_list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._action_list.setGridSize(_TILE_SIZE)
        self._action_list.setUniformItemSizes(True)
        self._action_list.setWordWrap(True)
        self._action_list.setDragEnabled(True)
        self._action_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._action_list, 1)

    def set_actions(self, actions: list[dict[str, Any]]) -> None:
        """Replace the full action list and reapply the current search filter."""
        self._actions = actions
        self._icons = {}
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        self._action_list.clear()
        needle = text.strip().lower()
        for action in self._actions:
            name = action.get("action_name", "")
            if needle and needle not in name.lower():
                continue
            item = QListWidgetItem(self._icon_for(action), name)
            item.setData(Qt.ItemDataRole.UserRole, action)
            plugin_name = action.get("plugin_name", "")
            item.setToolTip(f"{plugin_name}: {name}" if plugin_name else name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self._action_list.addItem(item)

    def _icon_for(self, action: dict[str, Any]) -> QIcon:
        key = (action.get("plugin_uuid", ""), action.get("action_uuid", ""))
        if key not in self._icons:
            pixmap = action_pixmap(action, _ICON_SOURCE_SIZE)
            icon = QIcon(pixmap)
            icon.addPixmap(pixmap, QIcon.Mode.Selected)  # keep the icon untinted on the selected tile
            self._icons[key] = icon
        return self._icons[key]
