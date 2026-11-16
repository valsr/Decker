"""Non-modal settings dialog with General, Server, UI and Plugins tabs, applied with an Apply button."""

from typing import Any

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from decker.client import config as client_config
from decker.client.assets import read_custom_stylesheet, resolve_theme
from decker.client.context import AppContext
from decker.client.themes import ThemeColors, apply_theme
from decker.client.widgets.plugins_tab import PluginsTab

_STATUS_REFRESH_MS = 1000
_THEME_LABELS: dict[str, str] = {
    client_config.THEME_DARK: "Dark",
    client_config.THEME_LIGHT: "Light",
    client_config.THEME_CUSTOM: "Custom…",
}
_STATE_LABELS: dict[str, str] = {
    "disconnected": "Disconnected",
    "initializing": "Connected, loading…",
    "unhealthy": "Connected, server unhealthy",
    "healthy": "Connected",
}


class SettingsDialog(QDialog):  # pylint: disable=too-many-instance-attributes
    """Client settings. Edits are staged until Apply; Close or Esc discards unapplied edits.

    While open, the connection status and the failed-plugin list update live.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(False)

        self._host_input: QLineEdit = QLineEdit()
        self._port_input: QLineEdit = QLineEdit()
        self._status_label: QLabel = QLabel()
        self._theme_combo: QComboBox = QComboBox()
        self._custom_path_input: QLineEdit = QLineEdit()
        self._browse_btn: QPushButton = QPushButton("Browse…")
        self._plugins_tab: PluginsTab = PluginsTab()
        self._failed_list = self._plugins_tab._failed_list  # pylint: disable=protected-access
        self._no_failures_label = self._plugins_tab._no_failures_label  # pylint: disable=protected-access
        self._message_label: QLabel = QLabel()
        self._buttons: QDialogButtonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close
        )

        self._close_to_tray_check: QCheckBox = QCheckBox("Close to tray")

        self._tabs: QTabWidget = QTabWidget()
        self._general_tab = self._build_general_tab()
        self._server_tab = self._build_server_tab()
        self._ui_tab = self._build_ui_tab()
        self._tabs.addTab(self._general_tab, "General")
        self._tabs.addTab(self._server_tab, "Server")
        self._tabs.addTab(self._ui_tab, "UI")
        self._tabs.addTab(self._plugins_tab, "Plugins")

        self._buttons.rejected.connect(self.reject)
        apply_btn = self._buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_btn is not None:
            apply_btn.clicked.connect(self.apply)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self._message_label, 1)
        bottom_row.addWidget(self._buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs, 1)
        layout.addLayout(bottom_row)
        self.resize(520, 520)

        self._status_timer: QTimer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)

    def open_dialog(self) -> None:
        """Load current settings into the form and show the dialog, or raise it if already open."""
        if not self.isVisible():
            self._load_from_config()
            self._plugins_tab.refresh()
        self.show()
        self.raise_()
        self.activateWindow()

    def apply(self) -> bool:
        """Validate all tabs, then save and apply them. Returns False and saves nothing on error."""
        host = self._host_input.text().strip()
        port = _parse_port(self._port_input.text())
        if not host or port is None:
            return self._fail(self._server_tab, "Enter a host and a port between 1 and 65535.")
        theme = self._selected_theme()
        custom_path = self._custom_path_input.text().strip()
        if theme == client_config.THEME_CUSTOM and not custom_path:
            return self._fail(self._ui_tab, "Choose a stylesheet file for the custom theme.")
        colors: ThemeColors | None = None
        if theme == client_config.THEME_CUSTOM:
            stylesheet = read_custom_stylesheet(custom_path)
            if stylesheet is None:
                return self._fail(self._ui_tab, f"Cannot read stylesheet: {custom_path}")
        else:
            stylesheet, colors = resolve_theme(theme)

        self._apply_server(host, port)
        client_config.set_close_to_tray(self._close_to_tray_check.isChecked())
        client_config.set_theme(theme, custom_path)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, stylesheet, colors)
        self._show_message("Applied.", "success")
        return True

    def set_failed_plugins(self, failures: dict[str, str]) -> None:
        """Replace the failed-plugin list (plugin UUID → error message)."""
        self._plugins_tab.set_failed_plugins(failures)

    def showEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Start live status updates while visible."""
        super().showEvent(a0)
        self._refresh_status()
        self._status_timer.start(_STATUS_REFRESH_MS)

    def hideEvent(self, a0: Any) -> None:  # pylint: disable=invalid-name
        """Stop live status updates while hidden."""
        self._status_timer.stop()
        super().hideEvent(a0)

    def _build_general_tab(self) -> QWidget:
        self._close_to_tray_check.setToolTip(
            "Closing the window keeps Decker running in the system tray. Use Quit in the tray menu to exit."
        )
        hint = QLabel("When off, closing the window quits Decker.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(self._close_to_tray_check)
        layout.addWidget(hint)
        layout.addStretch()
        return tab

    def _build_server_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.addRow("Host", self._host_input)
        form.addRow("Port", self._port_input)
        form.addRow("Status", self._status_label)
        return tab

    def _build_ui_tab(self) -> QWidget:
        for theme, label in _THEME_LABELS.items():
            self._theme_combo.addItem(label, theme)
        self._theme_combo.currentIndexChanged.connect(self._update_custom_enabled)
        self._custom_path_input.setPlaceholderText("Path to a .qss file")
        self._browse_btn.clicked.connect(self._browse_stylesheet)

        path_row = QHBoxLayout()
        path_row.addWidget(self._custom_path_input, 1)
        path_row.addWidget(self._browse_btn)

        tab = QWidget()
        form = QFormLayout(tab)
        form.addRow("Theme", self._theme_combo)
        form.addRow("Stylesheet", path_row)
        return tab

    def _load_from_config(self) -> None:
        self._close_to_tray_check.setChecked(client_config.get_close_to_tray())
        self._host_input.setText(client_config.get_server_host())
        self._port_input.setText(str(client_config.get_server_port()))
        index = self._theme_combo.findData(client_config.get_theme())
        self._theme_combo.setCurrentIndex(max(index, 0))
        self._custom_path_input.setText(client_config.get_custom_style_sheet())
        self._update_custom_enabled()
        self._message_label.clear()

    def _apply_server(self, host: str, port: int) -> None:
        if host == client_config.get_server_host() and port == client_config.get_server_port():
            return
        client_config.set_server(host, port)
        connection_manager = AppContext.get().connection_manager
        if connection_manager is not None:
            connection_manager.request_reconnect()

    def _selected_theme(self) -> str:
        return str(self._theme_combo.currentData())

    def _update_custom_enabled(self) -> None:
        custom = self._selected_theme() == client_config.THEME_CUSTOM
        self._custom_path_input.setEnabled(custom)
        self._browse_btn.setEnabled(custom)

    def _browse_stylesheet(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose stylesheet", "", "Qt stylesheets (*.qss);;All files (*)")
        if path:
            self._custom_path_input.setText(path)

    def _refresh_status(self) -> None:
        connection_manager = AppContext.get().connection_manager
        state = str(connection_manager.state) if connection_manager is not None else "disconnected"
        self._status_label.setText(_STATE_LABELS.get(state, state))

    def _fail(self, tab: QWidget, message: str) -> bool:
        self._tabs.setCurrentWidget(tab)
        self._show_message(message, "error")
        return False

    def _show_message(self, message: str, role: str) -> None:
        self._message_label.setProperty("role", role)
        self._message_label.setText(message)
        style = self._message_label.style()
        if style is not None:
            style.unpolish(self._message_label)
            style.polish(self._message_label)


def _parse_port(text: str) -> int | None:
    try:
        port = int(text.strip())
    except ValueError:
        return None
    return port if 0 < port < 65536 else None
