"""Dashboard view — the main working surface: sidebar, page pills, key grid, config panel."""

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from decker.client.context import AppContext
from decker.client.events import (
    ActionListUpdatedEvent,
    AppEvent,
    DeviceListUpdatedEvent,
    KeyDisplayStatesUpdatedEvent,
)
from decker.client.mock_page_model import MockPageModel
from decker.client.ui_state_store import UiStateStore
from decker.client.view_name import ViewName
from decker.client.views.base import BaseView
from decker.client.widgets.action_config_panel import ActionConfigPanel
from decker.client.widgets.button_grid import ButtonGridWidget
from decker.client.widgets.device_switcher_popup import DeviceSwitcherPopup
from decker.client.widgets.page_pill_bar import PagePillBar
from decker.client.widgets.sidebar import SidebarWidget
from decker.common.model import DeviceHardwareInfo

_DEFAULT_SIDEBAR_WIDTH = 240
_DEFAULT_KEY_COUNT = 15

_SPLITTER_MAIN_KEY = "splitter_main"
_SPLITTER_CONTENT_KEY = "splitter_content"
_SIDEBAR_COLLAPSED_KEY = "sidebar_collapsed"


class DashboardView(BaseView):  # pylint: disable=too-many-instance-attributes
    """Sidebar | (page pills + key grid / config panel), with persisted splitter layout."""

    def __init__(self, ui_state_store: UiStateStore | None = None) -> None:
        super().__init__()
        self.resize(900, 700)
        self._ui_state_store = ui_state_store or UiStateStore()
        self._devices: list[DeviceHardwareInfo] = []
        self._active_device_id: str | None = None
        self._last_expanded_sidebar_width = _DEFAULT_SIDEBAR_WIDTH
        self._page_model = MockPageModel(key_count=_DEFAULT_KEY_COUNT)
        self._device_popup: DeviceSwitcherPopup | None = None
        self._selected_key: int | None = None
        self._key_slots: dict[int, dict[str, Any]] = {}  # key_index → assignment metadata

        self._sidebar = SidebarWidget()
        self._pill_bar = PagePillBar()
        # Get device configuration

        self._grid = ButtonGridWidget()
        self._config_panel = ActionConfigPanel()

        self._content_splitter = QSplitter(Qt.Orientation.Vertical)
        self._content_splitter.addWidget(self._grid)
        self._content_splitter.addWidget(self._config_panel)
        self._content_splitter.setChildrenCollapsible(False)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._pill_bar)
        content_layout.addWidget(self._content_splitter)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.addWidget(self._sidebar)
        self._main_splitter.addWidget(content_widget)
        self._main_splitter.setCollapsible(0, True)
        self._main_splitter.setCollapsible(1, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._main_splitter)

        self._main_splitter.resize(self.size())
        self._content_splitter.resize(self._main_splitter.size())

        self._wire_signals()
        self._pill_bar.set_pages(self._page_model.pages)
        self._restore_state()

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def handle_event(self, event: AppEvent) -> bool | None:
        if isinstance(event, DeviceListUpdatedEvent):
            self._on_devices_updated(event.devices)
        elif isinstance(event, ActionListUpdatedEvent):
            self._sidebar.set_actions(event.actions)
        elif isinstance(event, KeyDisplayStatesUpdatedEvent):
            self._on_display_states_updated(event.device_id, event.states)
        return None

    def save_state(self) -> None:
        """Persist splitter sizes and sidebar-collapsed state to config.db."""
        self._ui_state_store.set(_SPLITTER_MAIN_KEY, self._main_splitter.sizes())
        self._ui_state_store.set(_SPLITTER_CONTENT_KEY, self._content_splitter.sizes())
        self._ui_state_store.set(_SIDEBAR_COLLAPSED_KEY, 1 if self._is_sidebar_collapsed() else 0)

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        self._pill_bar.sidebar_toggle_requested.connect(self._toggle_sidebar)
        self._grid.key_selected.connect(self._on_key_selected)
        self._grid.key_long_pressed.connect(self._on_key_long_pressed)
        self._grid.action_dropped.connect(self._on_action_dropped)
        self._sidebar.device_switcher_clicked.connect(self._show_device_switcher)
        self._sidebar.settings_clicked.connect(self._open_settings)

    # ------------------------------------------------------------------
    # Persisted layout state
    # ------------------------------------------------------------------

    def _restore_state(self) -> None:
        splitter_main = self._ui_state_store.get(_SPLITTER_MAIN_KEY)
        if splitter_main:
            self._main_splitter.setSizes(splitter_main)
            if splitter_main[0] > 0:
                self._last_expanded_sidebar_width = splitter_main[0]
        splitter_content = self._ui_state_store.get(_SPLITTER_CONTENT_KEY)
        if splitter_content:
            self._content_splitter.setSizes(splitter_content)
        if self._ui_state_store.get(_SIDEBAR_COLLAPSED_KEY):
            self._collapse_sidebar()

    def _is_sidebar_collapsed(self) -> bool:
        return self._main_splitter.sizes()[0] == 0

    def _toggle_sidebar(self) -> None:
        if self._is_sidebar_collapsed():
            self._expand_sidebar()
        else:
            self._collapse_sidebar()

    def _collapse_sidebar(self) -> None:
        sizes = self._main_splitter.sizes()
        if sizes[0] > 0:
            self._last_expanded_sidebar_width = sizes[0]
        self._main_splitter.setSizes([0, sum(sizes)])

    def _expand_sidebar(self) -> None:
        sizes = self._main_splitter.sizes()
        total = sum(sizes)
        width = min(self._last_expanded_sidebar_width, total)
        self._main_splitter.setSizes([width, total - width])

    # ------------------------------------------------------------------
    # Devices and key grid
    # ------------------------------------------------------------------

    def _on_devices_updated(self, devices: list[DeviceHardwareInfo]) -> None:
        self._devices = devices
        active_device = AppContext.get().active_device
        if active_device is None and devices:
            active_device = devices[0]
            window = AppContext.get().window
            if window is not None:
                window.set_active_device(active_device)
        self._refresh_grid_for_device(active_device)

    def _refresh_grid_for_device(self, device: DeviceHardwareInfo | None) -> None:
        device_id = device.id if device is not None else None
        if device_id == self._active_device_id:
            return
        self._active_device_id = device_id
        self._key_slots = {}
        self._selected_key = None
        self._config_panel.show_placeholder()
        keys = device.keys if device is not None else []
        key_count = device.num_keys if device is not None else _DEFAULT_KEY_COUNT
        self._page_model = MockPageModel(key_count=key_count)
        self._grid.build(keys)
        self._pill_bar.set_pages(self._page_model.pages)

    def _show_device_switcher(self) -> None:
        popup = DeviceSwitcherPopup(self._devices, parent=self)
        popup.device_selected.connect(self._on_device_selected)
        popup.show_above(self._sidebar.device_switcher_button)
        self._device_popup = popup

    def _on_device_selected(self, device: DeviceHardwareInfo) -> None:
        window = AppContext.get().window
        if window is not None:
            window.set_active_device(device)
        self._refresh_grid_for_device(device)

    # ------------------------------------------------------------------
    # Key grid interactions
    # ------------------------------------------------------------------

    def _on_key_selected(self, index: int) -> None:
        self._selected_key = index
        slot = self._key_slots.get(index)
        if slot is not None:
            self._config_panel.show_counter_config(
                slot.get("settings", {}),
                self._make_save_callback(index),
            )
        else:
            self._config_panel.show_placeholder()
        # Simulate a short press so the counter increments.
        device_id = AppContext.get().active_device_id
        if device_id and index in self._key_slots:
            cm = AppContext.get().connection_manager
            if cm is not None:
                cm.call("key_simulate_press", device_id, index)

    def _on_key_long_pressed(self, index: int) -> None:
        device_id = AppContext.get().active_device_id
        if not device_id or index not in self._key_slots:
            return
        cm = AppContext.get().connection_manager
        if cm is not None:
            cm.call("key_simulate_long_press", device_id, index)

    def _on_action_dropped(self, key_index: int, action_data: Any) -> None:
        device_id = AppContext.get().active_device_id
        if not device_id:
            return
        plugin_uuid = str(action_data.get("plugin_uuid", ""))
        action_uuid = str(action_data.get("action_uuid", ""))
        if not plugin_uuid or not action_uuid:
            return
        context_id = uuid.uuid4().hex
        settings: dict[str, Any] = {"step": 1, "max": 0}
        cm = AppContext.get().connection_manager
        if cm is None:
            return
        ok = cm.call(
            "key_assign",
            device_id,
            key_index,
            plugin_uuid,
            action_uuid,
            context_id,
            json.dumps(settings),
        )
        if ok:
            self._key_slots[key_index] = {
                "plugin_uuid": plugin_uuid,
                "action_uuid": action_uuid,
                "context_id": context_id,
                "settings": settings,
            }
            self._grid.set_key_label(key_index, "0")
            logging.debug("Assigned %s/%s to key %d", plugin_uuid, action_uuid, key_index)

    def _on_display_states_updated(self, device_id: str, states: list[dict[str, Any]]) -> None:
        if device_id != AppContext.get().active_device_id:
            return
        for state in states:
            key_index = int(state.get("key_index", -1))
            if key_index < 0:
                continue
            image_b64: str | None = state.get("image_b64")
            self._grid.set_key_image(key_index, image_b64)
            if not image_b64:
                self._grid.set_key_label(key_index, str(state.get("label", "")))
            # Keep slot metadata in sync with server state.
            if key_index not in self._key_slots:
                self._key_slots[key_index] = {
                    "plugin_uuid": str(state.get("plugin_uuid", "")),
                    "action_uuid": str(state.get("action_uuid", "")),
                    "context_id": str(state.get("context_id", "")),
                    "settings": dict(state.get("settings", {})),
                }
            else:
                self._key_slots[key_index]["settings"] = dict(state.get("settings", {}))
        # Refresh config panel if the selected key's state just changed.
        if self._selected_key is not None and self._selected_key in self._key_slots:
            slot = self._key_slots[self._selected_key]
            self._config_panel.show_counter_config(
                slot.get("settings", {}),
                self._make_save_callback(self._selected_key),
            )

    def _make_save_callback(self, key_index: int) -> "Callable[[dict[str, Any]], None]":
        def _cb(settings: dict[str, Any]) -> None:
            self._save_key_settings(key_index, settings)

        return _cb

    def _save_key_settings(self, key_index: int, settings: dict[str, Any]) -> None:
        device_id = AppContext.get().active_device_id
        if not device_id:
            return
        cm = AppContext.get().connection_manager
        if cm is None:
            return
        cm.call("key_update_settings", device_id, key_index, json.dumps(settings))
        if key_index in self._key_slots:
            self._key_slots[key_index]["settings"] = settings

    # ------------------------------------------------------------------
    # Other widget callbacks
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        window = AppContext.get().window
        if window is not None:
            window.switch_to(ViewName.SETTINGS)
