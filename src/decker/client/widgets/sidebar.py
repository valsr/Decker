"""Sidebar: searchable plugin actions (icon + name) in one collapsible section per plugin, dragged onto keys."""

import json
import math
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
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.action_icons import action_pixmap

_MIME_TYPE = "application/x-decker-action"
ICON_SIZE = 48
DRAG_ICON_SIZE = 56
_TILE_SIZE = QSize(96, 104)  # room for a two-line name under the icon
_ICON_SOURCE_SIZE = ICON_SIZE * 2  # rendered at 2x so icons stay sharp on high-DPI screens
_DRAG_FIELDS = ("plugin_uuid", "plugin_name", "action_uuid", "action_name")
BUILTIN_TITLE = "Built in"


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

    def fit_height(self) -> None:
        """Size the list to all its rows, so the sidebar scrolls as a whole instead of each section."""
        columns = max(1, self.viewport().width() // _TILE_SIZE.width())
        rows = math.ceil(self.count() / columns)
        self.setFixedHeight(rows * _TILE_SIZE.height() + 2 * self.frameWidth() + 4)

    def resizeEvent(self, e: Any) -> None:  # pylint: disable=invalid-name
        """Refit the height when the width changes the number of columns."""
        super().resizeEvent(e)
        self.fit_height()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # pylint: disable=invalid-name,unused-argument
        """Drag the current action by its icon."""
        item = self.currentItem()
        if item is not None:
            self.build_drag(item).exec(Qt.DropAction.CopyAction)


def _new_action_list() -> _DraggableActionList:
    action_list = _DraggableActionList()
    action_list.setObjectName("action-list")
    action_list.setViewMode(QListView.ViewMode.IconMode)
    action_list.setFlow(QListView.Flow.LeftToRight)
    action_list.setWrapping(True)
    action_list.setResizeMode(QListView.ResizeMode.Adjust)
    action_list.setMovement(QListView.Movement.Static)
    action_list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    action_list.setGridSize(_TILE_SIZE)
    action_list.setUniformItemSizes(True)
    action_list.setWordWrap(True)
    action_list.setDragEnabled(True)
    action_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
    action_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return action_list


class _Section(QWidget):
    """One plugin's header (click to fold) above its grid of action tiles."""

    def __init__(self, plugin_id: str, title: str, expanded: bool) -> None:
        super().__init__()
        self.plugin_id = plugin_id
        self.action_list = _new_action_list()
        self.header = QToolButton()
        self.header.setObjectName("sidebar-section")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header.toggled.connect(self._on_toggled)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.action_list)
        self._on_toggled(expanded)

    @property
    def expanded(self) -> bool:
        """Whether the grid is shown."""
        return self.header.isChecked()

    def _on_toggled(self, expanded: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.action_list.setVisible(expanded)


class SidebarWidget(QFrame):
    """Search-filterable plugin actions: a collapsible section per plugin, the built-in one first."""

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[dict[str, Any]] = []
        self._icons: dict[tuple[str, str], QIcon] = {}
        self._folded: set[str] = set()  # plugin ids the user collapsed; kept across refreshes and searches
        self._sections: list[_Section] = []

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search actions...")
        self._search.textChanged.connect(self._apply_filter)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._content)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._scroll, 1)

    @property
    def sections(self) -> list[tuple[str, list[str]]]:
        """``(title, action names)`` of every section shown, in order."""
        return [(s.header.text(), [s.action_list.item(i).text() for i in range(s.action_list.count())]) for s in self._sections]  # type: ignore[union-attr]

    def set_actions(self, actions: list[dict[str, Any]]) -> None:
        """Replace the full action list and reapply the current search filter."""
        self._actions = actions
        self._icons = {}
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for section in self._sections:
            self._content_layout.removeWidget(section)
            section.deleteLater()
        self._sections = []
        groups: dict[str, list[dict[str, Any]]] = {}
        for action in self._actions:
            if needle and needle not in action.get("action_name", "").lower():
                continue
            groups.setdefault(action.get("plugin_uuid", ""), []).append(action)
        for plugin_id in sorted(groups, key=lambda pid: self._order(pid, groups[pid])):
            self._add_section(plugin_id, groups[plugin_id])

    @staticmethod
    def _order(plugin_id: str, actions: list[dict[str, Any]]) -> tuple[bool, str]:
        builtin = any(a.get("plugin_builtin") for a in actions)
        return (not builtin, str(actions[0].get("plugin_name") or plugin_id).lower())

    def _add_section(self, plugin_id: str, actions: list[dict[str, Any]]) -> None:
        builtin = any(a.get("plugin_builtin") for a in actions)
        title = BUILTIN_TITLE if builtin else str(actions[0].get("plugin_name") or plugin_id)
        section = _Section(plugin_id, title, plugin_id not in self._folded)
        section.header.toggled.connect(lambda expanded, pid=plugin_id: self._remember_fold(pid, expanded))
        for action in actions:
            name = action.get("action_name", "")
            item = QListWidgetItem(self._icon_for(action), name)
            item.setData(Qt.ItemDataRole.UserRole, action)
            plugin_name = action.get("plugin_name", "")
            item.setToolTip(f"{plugin_name}: {name}" if plugin_name else name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            section.action_list.addItem(item)
        section.action_list.fit_height()
        self._content_layout.insertWidget(len(self._sections), section)
        self._sections.append(section)

    def _remember_fold(self, plugin_id: str, expanded: bool) -> None:
        (self._folded.discard if expanded else self._folded.add)(plugin_id)

    def _icon_for(self, action: dict[str, Any]) -> QIcon:
        key = (action.get("plugin_uuid", ""), action.get("action_uuid", ""))
        if key not in self._icons:
            pixmap = action_pixmap(action, _ICON_SOURCE_SIZE)
            icon = QIcon(pixmap)
            icon.addPixmap(pixmap, QIcon.Mode.Selected)  # keep the icon untinted on the selected tile
            self._icons[key] = icon
        return self._icons[key]
