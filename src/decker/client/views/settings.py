"""Settings view — server host/port configuration. Sub-navigation is deferred."""

from PyQt6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout

from decker.client import config as client_config
from decker.client.context import AppContext
from decker.client.views.base import BaseView


class SettingsView(BaseView):
    """Edits client.server_host and client.server_port. No other settings sections yet."""

    def __init__(self) -> None:
        super().__init__()
        self._host_input = QLineEdit()
        self._port_input = QLineEdit()
        self._saved_label = QLabel()
        self._saved_label.setProperty("role", "success")
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
        self._failed_plugins_label.setProperty("role", "error")
        layout.addWidget(self._failed_plugins_label)

        layout.addStretch()

    def on_activate(self) -> None:
        self._host_input.setText(client_config.get_server_host())
        self._port_input.setText(str(client_config.get_server_port()))
        self._saved_label.setVisible(False)

    def on_deactivate(self) -> None:
        self._saved_label.setVisible(False)

    def _on_save(self) -> None:
        host = self._host_input.text().strip()
        port = _parse_port(self._port_input.text())
        if not host or port is None:
            self._saved_label.setProperty("role", "error")
            self._saved_label.setText("Enter a host and a port between 1 and 65535.")
            self._saved_label.setVisible(True)
            return
        client_config.set_server(host, port)
        connection_manager = AppContext.get().connection_manager
        if connection_manager is not None:
            connection_manager.request_reconnect()
        self._saved_label.setProperty("role", "success")
        self._saved_label.setText("Saved.")
        self._saved_label.setVisible(True)


def _parse_port(text: str) -> int | None:
    try:
        port = int(text.strip())
    except ValueError:
        return None
    return port if 0 < port < 65536 else None
