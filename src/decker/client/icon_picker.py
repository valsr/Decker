"""Icon picker: choose a local file or browse an installed icon pack."""

import shutil
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)

from decker.asset.iconpack import IconPackManager
from decker.asset.paths import ensure_asset_dirs, user_icons_dir

_IMAGE_FILE_FILTER = "Images (*.svg *.png *.jpg *.jpeg *.gif *.webp)"
_ICON_EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp")


def copy_to_user_icons(source_path: Path) -> Path:
    """Copy source_path into ~/.decker/assets/user-icons/, creating the directory if needed."""
    ensure_asset_dirs()
    dest_path = user_icons_dir() / source_path.name
    shutil.copy2(source_path, dest_path)
    return dest_path


def list_pack_icons(pack_path: Path) -> list[Path]:
    """Return all image files directly inside an icon pack directory, sorted by name."""
    if not pack_path.is_dir():
        return []
    return sorted(p for p in pack_path.iterdir() if p.suffix.lower() in _ICON_EXTENSIONS)


class IconPackBrowserDialog(QDialog):
    """Two-pane dialog: installed icon packs on the left, that pack's icons on the right."""

    def __init__(self, parent: QWidget | None = None, icon_pack_manager: IconPackManager | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose icon from pack")
        self.selected_path: Path | None = None
        self._manager = icon_pack_manager or IconPackManager()

        self._pack_list = QListWidget()
        self._icon_list = QListWidget()
        self._pack_list.currentItemChanged.connect(self._on_pack_selected)
        self._icon_list.itemDoubleClicked.connect(self._on_icon_chosen)

        layout = QHBoxLayout(self)
        layout.addWidget(self._pack_list, 1)
        layout.addWidget(self._icon_list, 2)

        self._populate_packs()

    def _populate_packs(self) -> None:
        for pack in self._manager.list_packs():
            item = QListWidgetItem(pack["name"])
            item.setData(1, pack["path"])
            self._pack_list.addItem(item)

    def _on_pack_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._icon_list.clear()
        if current is None:
            return
        for icon_path in list_pack_icons(Path(current.data(1))):
            item = QListWidgetItem(icon_path.name)
            item.setData(1, str(icon_path))
            self._icon_list.addItem(item)

    def _on_icon_chosen(self, item: QListWidgetItem) -> None:
        self.selected_path = Path(item.data(1))
        self.accept()


class IconPickerWidget(QWidget):
    """Two-button icon picker: a local file, or an icon from an installed pack."""

    icon_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, icon_pack_manager: IconPackManager | None = None) -> None:
        super().__init__(parent)
        self._icon_pack_manager = icon_pack_manager

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
        dialog = IconPackBrowserDialog(self, self._icon_pack_manager)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_path is not None:
            self.icon_selected.emit(str(dialog.selected_path))
