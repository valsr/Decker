"""Icon picker: choose a local file or browse the icon packs installed on the server."""

import json
import shutil
from collections import deque
from pathlib import Path
from typing import Any, Protocol

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.asset.paths import ensure_asset_dirs, user_icons_dir
from decker.client.action_icons import decode_icon, placeholder_pixmap

_IMAGE_FILE_FILTER = "Images (*.svg *.png *.jpg *.jpeg *.gif *.webp)"
_THUMB_SIZE = 64
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


class IconPackBrowserDialog(QDialog):  # pylint: disable=too-few-public-methods
    """Two-pane dialog: icon packs installed on the server on the left, that pack's icons on the right."""

    icon_chosen = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None, connection_manager: "RpcCaller | None") -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose icon from pack")
        self._cm = connection_manager
        self._pixmaps: dict[tuple[str, str], QPixmap | None] = {}
        self._pending: deque[tuple[str, str, QListWidgetItem]] = deque()

        self._pack_list = QListWidget()
        self._icon_list = QListWidget()
        self._icon_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._icon_list.setIconSize(QSize(_THUMB_SIZE, _THUMB_SIZE))
        self._icon_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._status = QLabel()
        self._status.setProperty("role", "muted")
        self._pack_list.currentItemChanged.connect(self._on_pack_selected)
        self._icon_list.itemDoubleClicked.connect(self._on_icon_chosen)

        panes = QHBoxLayout()
        panes.addWidget(self._pack_list, 1)
        panes.addWidget(self._icon_list, 2)
        layout = QVBoxLayout(self)
        layout.addLayout(panes)
        layout.addWidget(self._status)

        self._populate_packs()

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
        for pack in packs:
            item = QListWidgetItem(str(pack.get("name", pack["id"])))
            item.setData(_DATA_ROLE, pack["id"])
            self._pack_list.addItem(item)

    def _on_pack_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._pending.clear()
        self._icon_list.clear()
        if current is None:
            return
        pack_id = str(current.data(_DATA_ROLE))
        names = self._call_json("iconpack_icons", pack_id)
        if not isinstance(names, list):
            self._status.setText("Couldn't load this pack's icons.")
            return
        self._status.setText("" if names else "This pack has no icons.")
        self._pending.clear()
        for name in names:
            item = QListWidgetItem(QIcon(self._cached_or_placeholder(pack_id, str(name))), Path(str(name)).stem)
            item.setData(_DATA_ROLE, str(name))
            self._icon_list.addItem(item)
            if (pack_id, str(name)) not in self._pixmaps:
                self._pending.append((pack_id, str(name), item))
        self._schedule_next_load()

    def _cached_or_placeholder(self, pack_id: str, name: str) -> QPixmap:
        return self._pixmaps.get((pack_id, name)) or placeholder_pixmap(name, _THUMB_SIZE)

    def _schedule_next_load(self) -> None:
        if self._pending:
            QTimer.singleShot(0, self._load_next_icon)

    def _load_next_icon(self) -> None:
        # One RPC per event-loop turn keeps the UI responsive over slow links.
        if not self._pending or self._cm is None:
            return
        pack_id, name, item = self._pending.popleft()
        raw = self._cm.call("iconpack_icon", pack_id, name)
        pixmap = decode_icon(raw) if isinstance(raw, str) else None
        self._pixmaps[(pack_id, name)] = pixmap
        if pixmap is not None:
            item.setIcon(QIcon(pixmap))
        self._schedule_next_load()

    def done(self, result: int) -> None:
        """Close the dialog, abandoning any icon loads still queued."""
        self._pending.clear()
        super().done(result)

    def _on_icon_chosen(self, item: QListWidgetItem) -> None:
        pack_item = self._pack_list.currentItem()
        if pack_item is None:
            return
        self.icon_chosen.emit(str(pack_item.data(_DATA_ROLE)), str(item.data(_DATA_ROLE)))
        self.accept()


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
        dialog = IconPackBrowserDialog(self, self.connection_manager)
        dialog.icon_chosen.connect(self.pack_icon_selected)
        dialog.exec()
