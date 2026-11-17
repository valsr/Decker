"""Icon picker: choose a local file or browse the icon packs installed on the server."""

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from decker.asset.paths import ensure_asset_dirs, user_icons_dir
from decker.client.action_icons import decode_icon, placeholder_pixmap
from decker.client.icon_cache import IconThumbnailCache, icon_cache
from decker.common.icon_ref import icon_display_name

_IMAGE_FILE_FILTER = "Images (*.svg *.png *.jpg *.jpeg *.gif *.webp)"
_THUMB_SIZE = 64
_FILTER_DELAY_MS = 150
_DATA_ROLE = Qt.ItemDataRole.UserRole


def copy_to_user_icons(source_path: Path) -> Path:
    """Copy source_path into ~/.decker/assets/user-icons/, creating the directory if needed."""
    ensure_asset_dirs()
    dest_path = user_icons_dir() / source_path.name
    shutil.copy2(source_path, dest_path)
    return dest_path


class RpcCaller(Protocol):  # pylint: disable=too-few-public-methods
    """The slice of ConnectionManager the picker needs."""

    def call(self, method: str, *args: Any) -> Any:
        """Call a server RPC; None on failure."""


class _IconModel(QAbstractListModel):
    """The icons on show: ``(pack id, path)`` entries; the decoration is asked for only when a row is painted."""

    def __init__(
        self,
        pixmap_for: Callable[[str, str], QPixmap],
        pack_label: Callable[[str], str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pixmap_for = pixmap_for
        self._pack_label = pack_label
        self._entries: list[tuple[str, str]] = []
        self._rows: dict[tuple[str, str], int] = {}

    def set_entries(self, entries: list[tuple[str, str]]) -> None:
        """Replace the icons on show."""
        self.beginResetModel()
        self._entries = entries
        self._rows = {entry: row for row, entry in enumerate(entries)}
        self.endResetModel()

    def entry(self, row: int) -> tuple[str, str] | None:
        """The ``(pack id, path)`` of a row, or None when out of range."""
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def refresh(self, entry: tuple[str, str]) -> None:
        """Repaint the row of ``entry`` (its icon arrived)."""
        row = self._rows.get(entry)
        if row is not None:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DecorationRole])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802  # pylint: disable=invalid-name
        """Number of icons on show."""
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Name, thumbnail (requested lazily) or tooltip of an icon."""
        entry = self.entry(index.row()) if index.isValid() else None
        if entry is None:
            return None
        pack_id, path = entry
        if role == Qt.ItemDataRole.DisplayRole:
            return icon_display_name(path)
        if role == Qt.ItemDataRole.DecorationRole:
            return self._pixmap_for(pack_id, path)
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{self._pack_label(pack_id)}: {path}"
        return None


def _blank_pixmap() -> QPixmap:
    pixmap = QPixmap(_THUMB_SIZE, _THUMB_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


class IconBrowserDialog(QDialog):  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """Icon browser: packs grouped by plugin on the left; a searchable thumbnail grid on the right."""

    icon_chosen = pyqtSignal(str, str)

    def __init__(
        self,
        parent: QWidget | None,
        connection_manager: "RpcCaller | None",
        tint: str | None = None,
        cache: IconThumbnailCache | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose icon")
        self.resize(820, 520)
        self._cm = connection_manager
        self._tint = tint or self.palette().text().color().name()
        self._cache = cache if cache is not None else icon_cache()
        self._packs: list[dict[str, Any]] = []
        self._names: dict[str, list[str]] = {}
        self._pixmaps: dict[tuple[str, str], QPixmap] = {}
        self._pending: list[tuple[str, str]] = []  # newest request first out: what is on screen now
        self._queued: set[tuple[str, str]] = set()
        self._load_scheduled = False
        self._blank = _blank_pixmap()

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search icons by name")
        self._search.setClearButtonEnabled(True)
        self._model = _IconModel(self._pixmap_for, self._pack_label, self)
        self._icon_list = QListView()
        self._icon_list.setModel(self._model)
        self._icon_list.setViewMode(QListView.ViewMode.IconMode)
        self._icon_list.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))
        self._icon_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._icon_list.setMovement(QListView.Movement.Static)
        self._icon_list.setUniformItemSizes(True)
        self._icon_list.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._status = QLabel()
        self._status.setProperty("role", "muted")
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(_FILTER_DELAY_MS)
        self._filter_timer.timeout.connect(self._refresh)
        self._search.textChanged.connect(self._on_search_edited)
        self._tree.currentItemChanged.connect(lambda _current, _previous: self._refresh())
        self._icon_list.doubleClicked.connect(self._on_activated)
        self._icon_list.activated.connect(self._on_activated)

        right = QVBoxLayout()
        right.addWidget(self._search)
        right.addWidget(self._icon_list)
        panes = QHBoxLayout()
        panes.addWidget(self._tree, 1)
        panes.addLayout(right, 3)
        layout = QVBoxLayout(self)
        layout.addLayout(panes)
        layout.addWidget(self._status)

        self._populate_packs()

    def _on_search_edited(self, _text: str) -> None:
        self._cancel_pending()  # what is on screen is about to change; do not fetch icons that will vanish
        self._filter_timer.start()

    def _call_json(self, method: str, *args: str) -> Any:
        if self._cm is None:
            return None
        raw = self._cm.call(method, *args)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def _populate_packs(self) -> None:
        packs = self._call_json("iconpacks_list")
        if not isinstance(packs, list):
            self._status.setText("Couldn't load icon packs from the server.")
            return
        if not packs:
            self._status.setText("No icon packs are installed on the server.")
            return
        self._packs = [p for p in packs if isinstance(p, dict) and "id" in p]
        try:
            self._cache.update_packs(self._packs)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Icon thumbnail cache could not be updated", exc_info=True)
        everything = QTreeWidgetItem(["All icons"])
        everything.setData(0, _DATA_ROLE, ("all", ""))
        self._tree.addTopLevelItem(everything)
        plugins: dict[str, QTreeWidgetItem] = {}
        for pack in self._packs:
            plugin_id = str(pack.get("plugin_id", ""))
            node = plugins.get(plugin_id)
            if node is None:
                node = QTreeWidgetItem([str(pack.get("plugin_name") or plugin_id)])
                node.setData(0, _DATA_ROLE, ("plugin", plugin_id))
                self._tree.addTopLevelItem(node)
                plugins[plugin_id] = node
            child = QTreeWidgetItem([str(pack.get("name", pack["id"]))])
            child.setData(0, _DATA_ROLE, ("pack", str(pack["id"])))
            node.addChild(child)
        self._tree.expandAll()
        self._tree.setCurrentItem(everything)

    def _selected_pack_ids(self) -> list[str]:
        item = self._tree.currentItem()
        kind, key = item.data(0, _DATA_ROLE) if item is not None else ("none", "")
        if kind == "all":
            return [str(p["id"]) for p in self._packs]
        if kind == "plugin":
            return [str(p["id"]) for p in self._packs if str(p.get("plugin_id", "")) == key]
        return [key] if kind == "pack" else []

    def _pack_label(self, pack_id: str) -> str:
        pack = next((p for p in self._packs if str(p["id"]) == pack_id), None)
        return str(pack.get("name", pack_id)) if pack is not None else pack_id

    def _pack_names(self, pack_id: str) -> list[str] | None:
        if pack_id not in self._names:
            names = self._call_json("iconpack_icons", pack_id)
            if not isinstance(names, list):
                return None
            self._names[pack_id] = [str(n) for n in names]
        return self._names[pack_id]

    def _refresh(self) -> None:
        self._cancel_pending()
        needle = self._search.text().strip().lower()
        entries: list[tuple[str, str]] = []
        failed = False
        for pack_id in self._selected_pack_ids():
            names = self._pack_names(pack_id)
            if names is None:
                failed = True
                continue
            entries += [(pack_id, n) for n in names if not needle or needle in icon_display_name(n).lower()]
        self._model.set_entries(entries)
        self._status.setText(_status_text(bool(entries), failed, bool(needle)))

    def _pixmap_for(self, pack_id: str, name: str) -> QPixmap:
        key = (pack_id, name)
        cached = self._pixmaps.get(key)
        if cached is not None:
            return cached
        stored = self._cache_get(pack_id, name)
        if stored is not None:
            self._pixmaps[key] = stored
            return stored
        if key not in self._queued:
            self._queued.add(key)
            self._pending.append(key)
            self._schedule_next_load()
        return self._blank

    def _cache_get(self, pack_id: str, name: str) -> QPixmap | None:
        try:
            return self._cache.get(pack_id, name, _THUMB_SIZE, self._tint)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Icon thumbnail cache lookup failed", exc_info=True)
            return None

    def _cache_put(self, pack_id: str, name: str, pixmap: QPixmap) -> None:
        try:
            self._cache.put(pack_id, name, _THUMB_SIZE, self._tint, pixmap)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Icon thumbnail cache store failed", exc_info=True)

    def _cancel_pending(self) -> None:
        self._pending.clear()
        self._queued.clear()

    def _schedule_next_load(self) -> None:
        if self._pending and not self._load_scheduled:
            self._load_scheduled = True
            QTimer.singleShot(0, self._load_next_icon)

    def _load_next_icon(self) -> None:
        # One RPC per event-loop turn keeps the UI responsive; the newest request (what is on screen) goes first.
        self._load_scheduled = False
        if not self._pending or self._cm is None:
            return
        key = self._pending.pop()
        self._queued.discard(key)
        raw = self._cm.call("iconpack_icon", *key)
        pixmap = decode_icon(raw, self._tint) if isinstance(raw, str) else None
        if pixmap is None:
            self._pixmaps[key] = placeholder_pixmap(key[1], _THUMB_SIZE)  # a letter tile, never cached
        else:
            thumb = pixmap.scaled(
                _THUMB_SIZE,
                _THUMB_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._pixmaps[key] = thumb
            self._cache_put(key[0], key[1], thumb)
        self._model.refresh(key)
        self._schedule_next_load()

    def done(self, result: int) -> None:
        """Close the dialog, abandoning any icon loads still queued."""
        self._cancel_pending()
        super().done(result)

    def _on_activated(self, index: QModelIndex) -> None:
        entry = self._model.entry(index.row())
        if entry is not None:
            self.icon_chosen.emit(*entry)
            self.accept()


def _status_text(has_entries: bool, failed: bool, searching: bool) -> str:
    if has_entries:
        return ""
    if failed:
        return "Couldn't load this pack's icons."
    return "No icons match." if searching else "This pack has no icons."


class IconPickerWidget(QWidget):  # pylint: disable=too-few-public-methods
    """Two-button icon picker: a local file, or an icon from an installed pack."""

    icon_selected = pyqtSignal(str)
    pack_icon_selected = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None, connection_manager: "RpcCaller | None" = None) -> None:
        super().__init__(parent)
        self.connection_manager = connection_manager

        choose_file_btn = QPushButton("Choose file...")
        choose_file_btn.clicked.connect(self._choose_file)
        from_pack_btn = QPushButton("From icon pack...")
        from_pack_btn.clicked.connect(self._browse_icon_packs)

        layout = QHBoxLayout(self)
        layout.addWidget(choose_file_btn)
        layout.addWidget(from_pack_btn)

    def _choose_file(self) -> None:
        path_str, _filter = QFileDialog.getOpenFileName(self, "Choose icon", "", _IMAGE_FILE_FILTER)
        if not path_str:
            return
        dest = copy_to_user_icons(Path(path_str))
        self.icon_selected.emit(str(dest))

    def _browse_icon_packs(self) -> None:
        dialog = IconBrowserDialog(self, self.connection_manager)
        dialog.icon_chosen.connect(self.pack_icon_selected)
        dialog.exec()
