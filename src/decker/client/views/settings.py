"""Settings view — server host/port configuration. Sub-navigation is deferred."""

from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout

from decker.client.views.base import BaseView
from decker.common import config


class SettingsView(BaseView):
    """Edits client.server_host and client.server_port. No other settings sections yet."""

    def __init__(self) -> None:
        super().__init__()
        self._host_input = QLineEdit()
        self._port_input = QLineEdit()
        self._saved_label = QLabel()
        self._saved_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")
        self._saved_label.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Server host"))
        layout.addWidget(self._host_input)
        layout.addWidget(QLabel("Server port"))
        layout.addWidget(self._port_input)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn)
        layout.addWidget(self._saved_label)

        layout.addWidget(QLabel("Failed plugins"))
        self._failed_plugins_label = QLabel("(none)")
        self._failed_plugins_label.setStyleSheet("color: #f38ba8; font-size: 12px;")
        layout.addWidget(self._failed_plugins_label)

        layout.addStretch()

    def on_activate(self) -> None:
        self._host_input.setText(config.get_as("client.server_host", str))
        self._port_input.setText(str(config.get_as("client.server_port", int)))
        self._saved_label.setVisible(False)

    def on_deactivate(self) -> None:
        self._saved_label.setVisible(False)

    def _on_save(self) -> None:
        config.set("client.server_host", self._host_input.text().strip())
        config.set("client.server_port", int(self._port_input.text().strip()))
        self._saved_label.setText("Saved.")
        self._saved_label.setVisible(True)
