"""Button grid matching the active device's key layout."""

import math

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QPushButton, QWidget

# (rows, cols) for known Stream Deck key counts; unknown counts fall back to a near-square grid.
_KNOWN_LAYOUTS: dict[int, tuple[int, int]] = {
    6: (2, 3),
    8: (2, 4),
    15: (3, 5),
    32: (4, 8),
}


def grid_dimensions_for_key_count(key_count: int) -> tuple[int, int]:
    """Return (rows, cols) for key_count, using known Stream Deck layouts where possible."""
    if key_count <= 0:
        return (0, 0)
    if key_count in _KNOWN_LAYOUTS:
        return _KNOWN_LAYOUTS[key_count]
    cols = math.ceil(math.sqrt(key_count))
    rows = math.ceil(key_count / cols)
    return (rows, cols)


class KeyButtonWidget(QPushButton):
    """Placeholder square for one key on the grid."""

    def __init__(self, index: int) -> None:
        super().__init__(str(index + 1))
        self.setFixedSize(64, 64)
        self.index = index


class ButtonGridWidget(QWidget):
    """Renders a placeholder key grid sized from the active device's key count."""

    key_selected = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self._grid_layout = QGridLayout(self)
        self._key_count = 0

    @property
    def key_count(self) -> int:
        """The number of keys currently rendered."""
        return self._key_count

    def set_key_count(self, key_count: int) -> None:
        """Rebuild the grid for a device with key_count keys."""
        self._key_count = key_count
        while (item := self._grid_layout.takeAt(0)) is not None:
            if widget := item.widget():
                widget.deleteLater()

        _, cols = grid_dimensions_for_key_count(key_count)
        for index in range(key_count):
            row, col = divmod(index, cols) if cols else (0, 0)
            button = KeyButtonWidget(index)
            button.clicked.connect(lambda _checked=False, i=index: self.key_selected.emit(i))
            self._grid_layout.addWidget(button, row, col)
