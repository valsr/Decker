"""In-place name editor: Esc cancels; Enter or losing focus commits (editingFinished)."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QLineEdit


class RenameEdit(QLineEdit):
    """In-place name editor; Esc cancels, Enter or losing focus commits."""

    cancelled = pyqtSignal()

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:  # pylint: disable=invalid-name
        """Cancel on Esc; otherwise edit normally."""
        if a0 is not None and a0.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(a0)
