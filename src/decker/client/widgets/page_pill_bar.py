"""Page pill navigation bar: sidebar toggle, page pills, and a gear menu."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from decker.client.mock_page_model import PageData


class PagePillBar(QWidget):
    """One checkable pill per page (mutually exclusive), plus sidebar toggle and gear menu."""

    sidebar_toggle_requested = pyqtSignal()
    page_selected = pyqtSignal(str)
    add_page_requested = pyqtSignal()
    delete_page_requested = pyqtSignal()
    rename_page_requested = pyqtSignal()
    set_default_page_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._pills_by_page_id: dict[str, QPushButton] = {}

        self._toggle_button = QToolButton()
        self._toggle_button.setText("Sidebar")
        self._toggle_button.clicked.connect(self.sidebar_toggle_requested.emit)

        self._pill_layout = QHBoxLayout()

        self._gear_button = QToolButton()
        self._gear_button.setText("Page")
        self._gear_menu = QMenu(self._gear_button)
        self._gear_menu.addAction("Add Page", self.add_page_requested.emit)
        self._gear_menu.addAction("Delete Page", self.delete_page_requested.emit)
        self._gear_menu.addAction("Rename Page", self.rename_page_requested.emit)
        self._gear_menu.addAction("Set as Default", self.set_default_page_requested.emit)
        self._gear_button.setMenu(self._gear_menu)
        self._gear_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        layout = QHBoxLayout(self)
        layout.addWidget(self._toggle_button)
        layout.addLayout(self._pill_layout)
        layout.addStretch()
        layout.addWidget(self._gear_button)

    @property
    def gear_menu(self) -> QMenu:
        """The gear button's QMenu — Add/Delete/Rename Page, Set as Default."""
        return self._gear_menu

    @property
    def button_group(self) -> QButtonGroup:
        """The exclusive QButtonGroup holding every page pill."""
        return self._button_group

    def set_pages(self, pages: list[PageData]) -> None:
        """Replace all pills with one per page; the first page starts checked."""
        while (item := self._pill_layout.takeAt(0)) is not None:
            widget = item.widget()
            if isinstance(widget, QAbstractButton):
                self._button_group.removeButton(widget)
            if widget is not None:
                widget.deleteLater()
        self._pills_by_page_id.clear()

        for page in pages:
            pill = QPushButton(page.name)
            pill.setCheckable(True)
            pill.clicked.connect(lambda _checked=False, page_id=page.page_id: self.page_selected.emit(page_id))
            self._button_group.addButton(pill)
            self._pill_layout.addWidget(pill)
            self._pills_by_page_id[page.page_id] = pill

        if pages:
            self._pills_by_page_id[pages[0].page_id].setChecked(True)
