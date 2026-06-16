"""Collapsible sidebar: searchable plugin action list, plus theme/settings/device buttons."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
)


class SidebarWidget(QFrame):
    """Search-filterable plugin action list, plus a bottom row of theme/settings/device buttons."""

    theme_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    device_switcher_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._actions: list[dict[str, str]] = []

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search actions...")
        self._search.textChanged.connect(self._apply_filter)

        self._action_list = QListWidget()

        theme_btn = QToolButton()
        theme_btn.setText("Theme")
        theme_btn.clicked.connect(self.theme_clicked.emit)

        settings_btn = QToolButton()
        settings_btn.setText("Settings")
        settings_btn.clicked.connect(self.settings_clicked.emit)

        self._device_switcher_button = QToolButton()
        self._device_switcher_button.setText("Device")
        self._device_switcher_button.clicked.connect(self.device_switcher_clicked.emit)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(theme_btn)
        bottom_row.addWidget(settings_btn)
        bottom_row.addWidget(self._device_switcher_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._search)
        layout.addWidget(self._action_list)
        layout.addLayout(bottom_row)

    @property
    def device_switcher_button(self) -> QToolButton:
        """The device-switcher button, used as the DeviceSwitcherPopup's anchor."""
        return self._device_switcher_button

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
            item.setData(1, action.get("action_uuid", ""))
            self._action_list.addItem(item)
