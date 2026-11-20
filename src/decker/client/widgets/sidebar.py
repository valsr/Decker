"""Sidebar: searchable plugin cards (icon + name) in one collapsible section per plugin, dragged onto keys."""

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

from decker.client.card_icons import card_pixmap

_MIME_TYPE = "application/x-decker-card"
ICON_SIZE = 48
DRAG_ICON_SIZE = 56
_TILE_SIZE = QSize(96, 104)  # room for a two-line name under the icon
_ICON_SOURCE_SIZE = ICON_SIZE * 2  # rendered at 2x so icons stay sharp on high-DPI screens
_DRAG_FIELDS = ("plugin_uuid", "plugin_name", "card_uuid", "card_name")
BUILTIN_TITLE = "Built in"


class _DraggableCardList(QListWidget):
    """Icon-mode QListWidget whose drags carry the card as custom MIME data and show its icon."""

    def build_drag(self, item: QListWidgetItem) -> QDrag:
        """Create the drag for item: the card (without its icon bytes) as MIME data, its icon as the image."""
        card: dict[str, Any] = item.data(Qt.ItemDataRole.UserRole) or {}
        payload = {field: card[field] for field in _DRAG_FIELDS if field in card}
        mime = QMimeData()
        mime.setData(_MIME_TYPE, QByteArray(json.dumps(payload).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = card_pixmap(card, DRAG_ICON_SIZE)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        return drag

    def fit_height(self) -> None:
        """Size the list to all its rows, so the sidebar scrolls as a whole instead of each section."""
        viewport = self.viewport()
        columns = max(1, (viewport.width() if viewport is not None else _TILE_SIZE.width()) // _TILE_SIZE.width())
        rows = math.ceil(self.count() / columns)
        self.setFixedHeight(rows * _TILE_SIZE.height() + 2 * self.frameWidth() + 4)

    def resizeEvent(self, e: Any) -> None:  # pylint: disable=invalid-name
        """Refit the height when the width changes the number of columns."""
        super().resizeEvent(e)
        self.fit_height()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # pylint: disable=invalid-name,unused-argument
        """Drag the current card by its icon."""
        item = self.currentItem()
        if item is not None:
            self.build_drag(item).exec(Qt.DropAction.CopyAction)


def _new_card_list() -> _DraggableCardList:
    card_list = _DraggableCardList()
    card_list.setObjectName("card-list")
    card_list.setViewMode(QListView.ViewMode.IconMode)
    card_list.setFlow(QListView.Flow.LeftToRight)
    card_list.setWrapping(True)
    card_list.setResizeMode(QListView.ResizeMode.Adjust)
    card_list.setMovement(QListView.Movement.Static)
    card_list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    card_list.setGridSize(_TILE_SIZE)
    card_list.setUniformItemSizes(True)
    card_list.setWordWrap(True)
    card_list.setDragEnabled(True)
    card_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
    card_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return card_list


class _Section(QWidget):
    """One plugin's header (click to fold) above its grid of card tiles."""

    def __init__(self, plugin_id: str, title: str, expanded: bool) -> None:
        super().__init__()
        self.plugin_id = plugin_id
        self.card_list = _new_card_list()
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
        layout.addWidget(self.card_list)
        self._on_toggled(expanded)

    @property
    def expanded(self) -> bool:
        """Whether the grid is shown."""
        return self.header.isChecked()

    def _on_toggled(self, expanded: bool) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.card_list.setVisible(expanded)


class SidebarWidget(QFrame):
    """Search-filterable plugin cards: a collapsible section per plugin, the built-in one first."""

    def __init__(self) -> None:
        super().__init__()
        self._cards: list[dict[str, Any]] = []
        self._icons: dict[tuple[str, str], QIcon] = {}
        self._folded: set[str] = set()  # plugin ids the user collapsed; kept across refreshes and searches
        self._sections: list[_Section] = []

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search cards...")
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
        """``(title, card names)`` of every section shown, in order."""
        return [(s.header.text(), [s.card_list.item(i).text() for i in range(s.card_list.count())]) for s in self._sections]  # type: ignore[union-attr]

    def set_cards(self, cards: list[dict[str, Any]]) -> None:
        """Replace the full card list and reapply the current search filter."""
        self._cards = cards
        self._icons = {}
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for section in self._sections:
            self._content_layout.removeWidget(section)
            section.deleteLater()
        self._sections = []
        groups: dict[str, list[dict[str, Any]]] = {}
        for card in self._cards:
            if needle and needle not in card.get("card_name", "").lower():
                continue
            groups.setdefault(card.get("plugin_uuid", ""), []).append(card)
        for plugin_id in sorted(groups, key=lambda pid: self._order(pid, groups[pid])):
            self._add_section(plugin_id, groups[plugin_id])

    @staticmethod
    def _order(plugin_id: str, cards: list[dict[str, Any]]) -> tuple[bool, str]:
        builtin = any(a.get("plugin_builtin") for a in cards)
        return (not builtin, str(cards[0].get("plugin_name") or plugin_id).lower())

    def _add_section(self, plugin_id: str, cards: list[dict[str, Any]]) -> None:
        builtin = any(a.get("plugin_builtin") for a in cards)
        title = BUILTIN_TITLE if builtin else str(cards[0].get("plugin_name") or plugin_id)
        section = _Section(plugin_id, title, plugin_id not in self._folded)
        section.header.toggled.connect(lambda expanded, pid=plugin_id: self._remember_fold(pid, expanded))
        for card in cards:
            name = card.get("card_name", "")
            item = QListWidgetItem(self._icon_for(card), name)
            item.setData(Qt.ItemDataRole.UserRole, card)
            plugin_name = card.get("plugin_name", "")
            item.setToolTip(f"{plugin_name}: {name}" if plugin_name else name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            section.card_list.addItem(item)
        section.card_list.fit_height()
        self._content_layout.insertWidget(len(self._sections), section)
        self._sections.append(section)

    def _remember_fold(self, plugin_id: str, expanded: bool) -> None:
        (self._folded.discard if expanded else self._folded.add)(plugin_id)

    def _icon_for(self, card: dict[str, Any]) -> QIcon:
        key = (card.get("plugin_uuid", ""), card.get("card_uuid", ""))
        if key not in self._icons:
            pixmap = card_pixmap(card, _ICON_SOURCE_SIZE)
            icon = QIcon(pixmap)
            icon.addPixmap(pixmap, QIcon.Mode.Selected)  # keep the icon untinted on the selected tile
            self._icons[key] = icon
        return self._icons[key]
