"""Error view — shown on hard failures, with a full restart option."""

from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from decker.client.context import AppContext
from decker.client.views.base import BaseView


class ErrorView(BaseView):
    """Displays an error message and triggers a full client reset on Restart."""

    def __init__(self) -> None:
        super().__init__()
        self._message_label = QLabel()
        self._message_label.setStyleSheet("color: #f38ba8; font-size: 13px;")
        self._message_label.setWordWrap(True)
        restart_btn = QPushButton("Restart")
        restart_btn.clicked.connect(self._on_restart)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(self._message_label)
        layout.addWidget(restart_btn)
        layout.addStretch()

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def show_error(self, message: str) -> None:
        """Set the displayed error message."""
        self._message_label.setText(message)

    def _on_restart(self) -> None:
        window = AppContext.get().window
        if window is not None:
            window.restart()
