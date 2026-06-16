"""Bottom panel for configuring the selected key's action.

Native action forms and Property Inspector (QWebEngineView) pages are a future plan;
this only hosts the placeholder shown when no key is selected.
"""

from PyQt6.QtWidgets import QLabel, QStackedWidget


class ActionConfigPanel(QStackedWidget):
    """Page 0 is a placeholder label; further pages are added by a future plan."""

    def __init__(self) -> None:
        super().__init__()
        placeholder = QLabel("Select a key to configure")
        placeholder.setStyleSheet("color: #8e8e93; font-size: 12px;")
        self.addWidget(placeholder)
