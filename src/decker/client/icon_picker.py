"""Icon picker: choose a local file or browse the icon packs installed on the server."""

import json
import logging
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from decker.client.action_icons import decode_icon, placeholder_pixmap
from decker.client.icon_cache import IconThumbnailCache, icon_cache
from decker.client.icon_import_dialog import IconImportDialog
from decker.common.icon_ref import icon_display_name

_IMAGE_FILE_FILTER = "Images (*.svg *.png *.jpg *.jpeg *.gif)"
_THUMB_SIZE = 64
MAX_IMPORT_BYTES = 4 * 1024 * 1024  # the server's per-icon limit
_FILTER_DELAY_MS = 150
_DATA_ROLE = Qt.ItemDataRole.UserRole


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


def _kind_badge(pixmap: QPixmap, name: str) -> QPixmap:
    """A copy of ``pixmap`` with a third-size corner badge: a play button for GIFs, a colour wheel for SVGs."""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in ("gif", "svg") or pixmap.isNull():
        return pixmap
    result = QPixmap(pixmap)
    side = max(1, min(result.width(), result.height()) // 3)
    box = QRectF(result.width() - side, result.height() - side, side, side)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(255, 255, 255), max(1.0, side / 14)))
    if suffix == "gif":
        painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
        painter.drawEllipse(box)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        cx, cy, r = box.center().x(), box.center().y(), side * 0.25
        painter.drawPolygon(
            QPolygonF([QPointF(cx - r * 0.7, cy - r), QPointF(cx - r * 0.7, cy + r), QPointF(cx + r, cy)])
        )
    else:
        wheel = QConicalGradient(box.center(), 90)
        for stop in range(7):
            wheel.setColorAt(stop / 6, QColor.fromHsvF((1 - stop / 6) % 1.0 if stop < 6 else 0.0, 0.9, 1.0))
        painter.setBrush(QBrush(wheel))
        painter.drawEllipse(box)
    painter.end()
    return result


NO_TINT = ""  # pass as IconBrowserDialog's tint to show images as they are (e.g. backgrounds, which are never tinted)


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
        self.setWindowTitle("Choose image")
        self.resize(820, 520)
        self._cm = connection_manager
        self._tint: str | None = self.palette().text().color().name() if tint is None else (tint or None)
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
        self._search.setPlaceholderText("Search images by name")
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
            self._status.setText("Couldn't load the image library from the server.")
            return
        if not packs:
            self._status.setText("The image library is empty: no packs are installed on the server.")
            return
        self._packs = [p for p in packs if isinstance(p, dict) and "id" in p]
        try:
            self._cache.update_packs(self._packs)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Icon thumbnail cache could not be updated", exc_info=True)
        everything = QTreeWidgetItem(["All images"])
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
            stored = _kind_badge(stored, name)
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
            self._cache_put(key[0], key[1], thumb)
            self._pixmaps[key] = _kind_badge(thumb, key[1])
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
        return "Couldn't load this pack's images."
    return "No images match." if searching else "This pack has no images."


class IconPickerWidget(QWidget):  # pylint: disable=too-few-public-methods
    """Two-button icon picker: a local file, or an icon from an installed pack."""

    icon_selected = pyqtSignal(str)
    pack_icon_selected = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None, connection_manager: "RpcCaller | None" = None) -> None:
        super().__init__(parent)
        self.connection_manager = connection_manager

        choose_file_btn = QPushButton("Choose file...")
        choose_file_btn.clicked.connect(self._choose_file)
        from_pack_btn = QPushButton("From image library...")
        from_pack_btn.clicked.connect(self._browse_icon_packs)

        layout = QHBoxLayout(self)
        layout.addWidget(choose_file_btn)
        layout.addWidget(from_pack_btn)

    def _import_allowed(self) -> bool:
        if self.connection_manager is None:
            return False
        try:
            return bool(self.connection_manager.call("plugin_install_allowed"))
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    def _choose_file(self) -> None:
        if self.connection_manager is None or not self._import_allowed():
            QMessageBox.information(self, "Import image", "Importing images needs a local connection to the server.")
            return
        path_str, _filter = QFileDialog.getOpenFileName(self, "Choose image", "", _IMAGE_FILE_FILTER)
        if not path_str:
            return
        path = Path(path_str)
        data = self._read_icon_file(path)
        if data is None:
            return
        dialog = IconImportDialog(self, self.connection_manager, path.name, data)
        dialog.imported.connect(lambda file: self.pack_icon_selected.emit("decker.user", file))
        dialog.exec()

    def _read_icon_file(self, path: Path) -> bytes | None:
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                QMessageBox.warning(self, "Import image", f"{path.name} is not a regular file.")
                return None
            if info.st_size <= MAX_IMPORT_BYTES:
                with path.open("rb") as handle:
                    data = handle.read(MAX_IMPORT_BYTES + 1)
                if len(data) <= MAX_IMPORT_BYTES:
                    return data
        except OSError as exc:
            QMessageBox.warning(self, "Import image", f"Cannot read {path.name}: {exc}")
            return None
        QMessageBox.warning(self, "Import image", f"{path.name} is larger than 4 MiB and cannot be imported.")
        return None

    def _browse_icon_packs(self) -> None:
        dialog = IconBrowserDialog(self, self.connection_manager)
        dialog.icon_chosen.connect(self.pack_icon_selected)
        dialog.exec()
