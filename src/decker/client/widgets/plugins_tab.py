"""Settings → Plugins tab: installed plugins, install/uninstall, global settings and load failures."""

import base64
import json
import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from decker.client.context import AppContext
from decker.client.events import (
    PluginInstallFinishedEvent,
    PluginInstallProgressEvent,
    PluginLoadFailedEvent,
    PluginsChangedEvent,
)
from decker.client.events.event_manager import EventManager
from decker.client.widgets.schema_form import SchemaForm

PACKAGE_SUFFIX = ".deckerplugin"
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
TRUST_NOTICE = "Plugins run with your user's permissions. Only install plugins from authors you trust."
NOT_ALLOWED_TOOLTIP = "Installing plugins is only allowed from the server's own machine"
_PLUGIN_ID_ROLE = Qt.ItemDataRole.UserRole


def install_allowed() -> bool:
    """Whether the connected server accepts plugin installs from this client."""
    manager = AppContext.get().connection_manager
    return manager is not None and bool(manager.call("plugin_install_allowed"))


def install_package_file(path: Path, parent: QWidget | None = None) -> None:
    """Confirm (with the trust notice) and send a .deckerplugin file to the server for installation."""
    manager = AppContext.get().connection_manager
    if manager is None:
        QMessageBox.warning(parent, "Install plugin", "Not connected to the server.")
        return
    try:
        too_large = path.stat().st_size > MAX_PACKAGE_BYTES
    except OSError as exc:
        QMessageBox.warning(parent, "Install plugin", f"Cannot read {path.name}: {exc}")
        return
    if too_large:
        QMessageBox.warning(parent, "Install plugin", f"{path.name} is larger than 64 MiB and cannot be installed.")
        return
    answer = QMessageBox.question(parent, "Install plugin", f"Install {path.name}?\n\n{TRUST_NOTICE}")
    if answer != QMessageBox.StandardButton.Yes:
        return
    try:
        data = path.read_bytes()
    except OSError as exc:
        QMessageBox.warning(parent, "Install plugin", f"Cannot read {path.name}: {exc}")
        return
    if not manager.call("plugin_install", path.name, data):
        QMessageBox.warning(parent, "Install plugin", f"The server refused to install {path.name}.")


def _contribution_summary(plugin: dict[str, Any]) -> str:
    parts = []
    for key, singular in (("actions", "action"), ("icon_packs", "icon pack")):
        count = int(plugin.get(key, 0))
        if count:
            parts.append(f"{count} {singular}{'' if count == 1 else 's'}")
    return " · ".join(parts) or "no contributions"


def _plugin_icon(plugin: dict[str, Any]) -> QIcon:
    pixmap = QPixmap()
    encoded = plugin.get("icon_b64")
    if encoded:
        pixmap.loadFromData(base64.b64decode(encoded))
    return QIcon(pixmap)


class PluginsTab(QWidget):  # pylint: disable=too-many-instance-attributes
    """Lists installed plugins and manages install, uninstall, global settings and load failures."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugins: dict[str, dict[str, Any]] = {}
        self._failed_plugins: dict[str, str] = {}

        self._plugin_list: QListWidget = QListWidget()
        self._install_btn: QPushButton = QPushButton("Install…")
        self._uninstall_btn: QPushButton = QPushButton("Uninstall")
        self._status_label: QLabel = QLabel()
        self._settings_form: SchemaForm = SchemaForm()
        self._apply_settings_btn: QPushButton = QPushButton("Apply plugin settings")
        self._settings_title: QLabel = QLabel("Plugin settings")
        self._failed_list: QListWidget = QListWidget()
        self._no_failures_label: QLabel = QLabel("No plugins failed to load.")
        self._selected_id: str | None = None

        self._build()
        em = EventManager.get()
        em.subscribe(PluginLoadFailedEvent, self._on_plugin_load_failed)
        em.subscribe(PluginInstallProgressEvent, self._on_install_progress)
        em.subscribe(PluginInstallFinishedEvent, self._on_install_finished)
        em.subscribe(PluginsChangedEvent, self._on_plugins_changed)

    def refresh(self) -> None:
        """Re-fetch the installed plugins and the install permission from the server."""
        manager = AppContext.get().connection_manager
        raw = manager.call("plugins_list") if manager is not None else None
        try:
            plugins: list[dict[str, Any]] = json.loads(raw) if raw else []
        except (ValueError, TypeError):
            plugins = []
        self._plugins = {str(p["id"]): p for p in plugins}
        self._render_plugins()
        allowed = install_allowed()
        self._install_btn.setEnabled(allowed)
        self._install_btn.setToolTip("" if allowed else NOT_ALLOWED_TOOLTIP)

    def set_failed_plugins(self, failures: dict[str, str]) -> None:
        """Replace the failed-plugin list (plugin UUID → error message)."""
        self._failed_plugins = dict(failures)
        self._refresh_failed_plugins()

    def _build(self) -> None:
        self._plugin_list.setIconSize(self._plugin_list.iconSize() * 2)
        self._plugin_list.currentItemChanged.connect(self._on_selection_changed)
        self._install_btn.clicked.connect(self._on_install_clicked)
        self._uninstall_btn.clicked.connect(self._on_uninstall_clicked)
        self._uninstall_btn.setEnabled(False)
        self._apply_settings_btn.clicked.connect(self._on_apply_settings)
        self._status_label.setWordWrap(True)
        self._status_label.setProperty("role", "muted")
        self._no_failures_label.setProperty("role", "muted")
        self._settings_title.setProperty("role", "title")
        self._set_settings_visible(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self._install_btn)
        buttons.addWidget(self._uninstall_btn)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(self._plugin_list, 2)
        layout.addLayout(buttons)
        layout.addWidget(self._status_label)
        layout.addWidget(self._settings_title)
        layout.addWidget(self._settings_form)
        layout.addWidget(self._apply_settings_btn)
        layout.addWidget(QLabel("Failed plugins"))
        layout.addWidget(self._no_failures_label)
        layout.addWidget(self._failed_list, 1)
        self._refresh_failed_plugins()

    def _render_plugins(self) -> None:
        self._plugin_list.blockSignals(True)
        self._plugin_list.clear()
        for plugin_id, plugin in sorted(self._plugins.items(), key=lambda kv: str(kv[1].get("name", kv[0])).lower()):
            kind = "bundled" if plugin.get("bundled") else "installed"
            text = (
                f"{plugin.get('name', plugin_id)}  v{plugin.get('version', '')} · {plugin.get('author', '')} · {kind}\n"
                f"{_contribution_summary(plugin)}"
            )
            item = QListWidgetItem(_plugin_icon(plugin), text)
            item.setData(_PLUGIN_ID_ROLE, plugin_id)
            item.setToolTip(str(plugin.get("description", "")))
            self._plugin_list.addItem(item)
            if plugin_id == self._selected_id:
                self._plugin_list.setCurrentItem(item)
        self._plugin_list.blockSignals(False)
        if self._selected_id not in self._plugins:
            self._selected_id = None
        self._show_selection()

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous: Any = None) -> None:
        self._selected_id = str(current.data(_PLUGIN_ID_ROLE)) if current is not None else None
        self._show_selection()

    def _show_selection(self) -> None:
        plugin = self._plugins.get(self._selected_id or "")
        self._uninstall_btn.setEnabled(plugin is not None and not plugin.get("bundled"))
        schema = plugin.get("global_settings_schema") if plugin else None
        if plugin is None or not schema:
            self._set_settings_visible(False)
            return
        self._settings_form.set_schema(schema, plugin.get("global_settings") or {})
        self._set_settings_visible(True)

    def _set_settings_visible(self, visible: bool) -> None:
        for widget in (self._settings_title, self._settings_form, self._apply_settings_btn):
            widget.setVisible(visible)

    def _on_install_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Install plugin", "", f"Decker plugins (*{PACKAGE_SUFFIX})")
        if path:
            install_package_file(Path(path), self)

    def _on_uninstall_clicked(self) -> None:
        plugin = self._plugins.get(self._selected_id or "")
        manager = AppContext.get().connection_manager
        if plugin is None or manager is None or plugin.get("bundled"):
            return
        count = int(manager.call("plugin_usage", plugin["id"]) or 0)
        answer = QMessageBox.question(
            self, "Uninstall plugin", f"{plugin['name']} is used on {count} keys. Uninstall it and clear those keys?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if manager.call("plugin_uninstall", plugin["id"]):
            self._status_label.setText(f"Uninstalled {plugin['name']}.")
        else:
            self._status_label.setText(f"Could not uninstall {plugin['name']}.")
        self.refresh()

    def _on_apply_settings(self) -> None:
        manager = AppContext.get().connection_manager
        if manager is None or self._selected_id is None:
            return
        values = json.dumps(self._settings_form.values())
        ok = manager.call("plugin_update_global_settings", self._selected_id, values)
        self._status_label.setText("Plugin settings applied." if ok else "Could not apply plugin settings.")
        if ok:
            self._plugins[self._selected_id]["global_settings"] = self._settings_form.values()

    def _on_install_progress(self, event: PluginInstallProgressEvent) -> None:
        self._status_label.setText(event.message)

    def _on_install_finished(self, event: PluginInstallFinishedEvent) -> None:
        if event.ok:
            if event.previous_version:
                text = f"Updated {event.plugin_id} from {event.previous_version} to {event.version}."
            else:
                text = f"Installed {event.plugin_id} {event.version}."
        else:
            text = f"Install failed: {event.message}"
        self._status_label.setText(text)
        logging.info("Plugin install %s finished: %s", event.job_id, text)

    def _on_plugins_changed(self, _event: PluginsChangedEvent) -> None:
        self.refresh()

    def _on_plugin_load_failed(self, event: PluginLoadFailedEvent) -> None:
        self._failed_plugins[event.plugin_uuid] = event.error
        self._refresh_failed_plugins()

    def _refresh_failed_plugins(self) -> None:
        self._failed_list.clear()
        for plugin_uuid, error in sorted(self._failed_plugins.items()):
            self._failed_list.addItem(f"{plugin_uuid}: {error}")
        self._no_failures_label.setVisible(not self._failed_plugins)
        self._failed_list.setVisible(bool(self._failed_plugins))
