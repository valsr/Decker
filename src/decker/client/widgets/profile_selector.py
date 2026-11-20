"""Profile dropdown: the active profile on a button, a popup to switch, rename (double-click), add and edit."""

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.assets import ICON_PATH
from decker.client.widgets.rename_edit import RenameEdit
from decker.common.icon_ref import DECKER_ICON_REF
from decker.common.model import ProfileInfo

IconProvider = Callable[[str], QIcon | None]
_ICON_SIZE = 18
_ROW_ID = Qt.ItemDataRole.UserRole


class _Popup(QFrame):
    """A frameless popup holding the profile list and the Add / Edit buttons."""

    def __init__(self, parent: QWidget, on_hide: Callable[[], None]) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("profilePopup")
        self._on_hide = on_hide
        self.list = QListWidget()
        self.list.setObjectName("profileList")
        self.list.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.add_button = QPushButton("+ Add profile")
        self.edit_button = QPushButton("Edit profile…")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.list)
        layout.addWidget(self.add_button)
        layout.addWidget(self.edit_button)

    def hideEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Leaving the popup accepts a rename in progress."""
        self._on_hide()
        super().hideEvent(a0)


class ProfileSelector(QToolButton):  # pylint: disable=too-many-instance-attributes
    """Shows the active profile; its popup lists profiles (click selects, double-click renames) plus Add and Edit."""

    profile_selected = pyqtSignal(int)
    add_requested = pyqtSignal()
    edit_requested = pyqtSignal(int)  # the active profile's id
    rename_requested = pyqtSignal(int, str)  # profile id, new name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("profileSelector")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.setToolTip("Profile")
        self._profiles: dict[int, str] = {}
        self._active_id = -1
        self._pending_id: int | None = None
        self._shown: tuple[tuple[ProfileInfo, ...], int] | None = None
        self._rename_id: int | None = None
        self._rename_edit: RenameEdit | None = None
        self._popup = _Popup(self, lambda: self._finish_rename(commit=True))
        self._select_timer = QTimer(self)
        self._select_timer.setSingleShot(True)
        self._select_timer.timeout.connect(self._commit_select)
        self.clicked.connect(self.show_popup)
        self.popup_list.itemClicked.connect(self._on_item_clicked)
        self.popup_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._add_button.clicked.connect(self._on_add)
        self._edit_button.clicked.connect(self._on_edit)

    @property
    def popup_list(self) -> QListWidget:
        """The popup's list of profiles; each row's UserRole data is the profile id."""
        return self._popup.list

    @property
    def _add_button(self) -> QPushButton:
        return self._popup.add_button

    @property
    def _edit_button(self) -> QPushButton:
        return self._popup.edit_button

    def set_profiles(
        self, profiles: list[ProfileInfo], active_profile_id: int, icon_for: IconProvider | None = None
    ) -> None:
        """Rebuild the list in the given order and show the active profile on the button.

        An identical list changes nothing, so a rename in progress survives refreshes caused by page changes.
        """
        signature = (tuple(profiles), active_profile_id)
        if signature == self._shown:
            return
        self._shown = signature
        self._finish_rename(commit=False)
        self.popup_list.blockSignals(True)
        self.popup_list.clear()
        self._profiles = {profile.profile_id: profile.name for profile in profiles}
        self._active_id = active_profile_id
        fallback = QIcon(str(ICON_PATH))
        for profile in profiles:
            item = QListWidgetItem(profile.name)
            item.setData(_ROW_ID, profile.profile_id)
            item.setIcon(profile_qicon(profile.icon, icon_for, fallback))
            self.popup_list.addItem(item)
            if profile.profile_id == active_profile_id:
                self.popup_list.setCurrentItem(item)
                self.setText(profile.name)
                self.setToolTip(profile.name)
                self.setIcon(item.icon())
        self.popup_list.blockSignals(False)

    def show_popup(self) -> None:
        """Open the popup under the button."""
        self._popup.move(self.mapToGlobal(self.rect().bottomLeft()))
        self._popup.show()

    def hide_popup(self) -> None:
        """Close the popup, accepting a rename in progress."""
        self._popup.hide()

    def start_rename(self, profile_id: int) -> None:
        """Open the in-place editor over a profile's row."""
        for row in range(self.popup_list.count()):
            item = self.popup_list.item(row)
            if item is not None and item.data(_ROW_ID) == profile_id:
                self._finish_rename(commit=False)
                edit = RenameEdit(self._profiles.get(profile_id, ""))
                edit.editingFinished.connect(lambda: self._finish_rename(commit=True))
                edit.cancelled.connect(lambda: self._finish_rename(commit=False))
                self.popup_list.setItemWidget(item, edit)
                self._rename_id, self._rename_edit = profile_id, edit
                edit.selectAll()
                edit.setFocus()
                return

    def _finish_rename(self, commit: bool) -> None:
        edit, profile_id = self._rename_edit, self._rename_id
        if edit is None or profile_id is None:
            return
        self._rename_edit = self._rename_id = None
        name = edit.text().strip()
        for row in range(self.popup_list.count()):
            item = self.popup_list.item(row)
            if item is not None and item.data(_ROW_ID) == profile_id:
                self.popup_list.removeItemWidget(item)
        edit.deleteLater()
        if commit and name and name != self._profiles.get(profile_id, ""):
            self.rename_requested.emit(profile_id, name)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._pending_id = item.data(_ROW_ID)
        self._select_timer.start(QApplication.doubleClickInterval())

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._select_timer.stop()
        self._pending_id = None
        self.start_rename(item.data(_ROW_ID))

    def _commit_select(self) -> None:
        profile_id, self._pending_id = self._pending_id, None
        if profile_id is None:
            return
        self.hide_popup()
        if profile_id != self._active_id:
            self.profile_selected.emit(profile_id)

    def _on_add(self) -> None:
        self.hide_popup()
        self.add_requested.emit()

    def _on_edit(self) -> None:
        self.hide_popup()
        self.edit_requested.emit(self._active_id)


def decker_fallback_icon() -> QIcon:
    """The Decker icon, shown for a profile without an icon of its own."""
    return QIcon(str(ICON_PATH))


def profile_qicon(ref: str, provider: IconProvider | None, fallback: QIcon | None = None) -> QIcon:
    """The icon for a profile's icon ref: the provider's, else the Decker icon."""
    fallback = fallback if fallback is not None else decker_fallback_icon()
    if ref in ("", DECKER_ICON_REF) or provider is None:
        return fallback
    icon = provider(ref)
    return icon if icon is not None and not icon.isNull() else fallback
