"""Tests for decker.client.views.dashboard.DashboardView."""

import dataclasses
import json
from typing import Any
from unittest.mock import MagicMock, patch

from assertpy import assert_that
from PyQt6.QtWidgets import QMessageBox

from decker.client.context import AppContext
from decker.client.events import (
    ActionListUpdatedEvent,
    DeviceListUpdatedEvent,
    KeyDisplayStatesUpdatedEvent,
    PagesUpdatedEvent,
)
from decker.client.ui_state_store import UiStateStore
from decker.client.views.dashboard import DashboardView, _confirm_delete_page
from decker.common.model import DeviceHardwareInfo, DevicePages, KeyInfo, PageInfo


def _make_keys(rows: int, cols: int) -> list[KeyInfo]:
    return [
        KeyInfo(row=r, col=c, pixel_width=72, pixel_height=72, type="key") for r in range(rows) for c in range(cols)
    ]


_KEYS_15 = _make_keys(3, 5)
_KEYS_6 = _make_keys(2, 3)

_D1 = DeviceHardwareInfo(id="aabbccdd", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15, keys=_KEYS_15)
_D2 = DeviceHardwareInfo(id="11223344", type="Stream Deck Mini", vendor_id=0, product_id=0, num_keys=6, keys=_KEYS_6)
_DEVICES = [_D1, _D2]
_PAGES = DevicePages(
    device_id="dev1",
    pages=[PageInfo("p1", "Page 1"), PageInfo("p2", "Page 2")],
    default_page_id="p1",
    active_page_id="p1",
)


def _make_view(tmp_path) -> DashboardView:
    return DashboardView(ui_state_store=UiStateStore(tmp_path / "config.db"))


class TestDashboardView:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_has_no_page_tabs_until_server_sends_pages(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        assert_that(view._page_tabs.tab_bar.count()).is_equal_to(0)  # pylint: disable=protected-access


class TestDeviceListHandling:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_auto_selects_first_device_when_none_active(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        mock_window.set_active_device.assert_called_once_with(_D1)

    def test_does_not_override_already_active_device(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = _D2
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        mock_window.set_active_device.assert_not_called()

    def test_grid_resizes_to_active_devices_key_count(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = _D2

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        assert_that(view._grid.key_count).is_equal_to(6)  # pylint: disable=protected-access

    def test_same_device_does_not_rebuild_grid(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = _D1
        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        with patch.object(view._grid, "build") as mock_build:  # pylint: disable=protected-access
            view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))
            mock_build.assert_not_called()


class TestActionListHandling:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_populates_sidebar_actions(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        actions = [{"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.a", "action_name": "A"}]

        view.handle_event(ActionListUpdatedEvent(actions=actions))

        assert_that(view._sidebar._actions).is_equal_to(actions)  # pylint: disable=protected-access


class TestSidebarToggle:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_toggle_collapses_sidebar_to_zero(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        view._main_splitter.setSizes([240, 760])  # pylint: disable=protected-access

        view._toggle_sidebar()  # pylint: disable=protected-access

        assert_that(view._main_splitter.sizes()[0]).is_equal_to(0)  # pylint: disable=protected-access

    def test_toggle_twice_restores_previous_width(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        view._main_splitter.setSizes([240, 760])  # pylint: disable=protected-access
        actual_width = view._main_splitter.sizes()[0]  # pylint: disable=protected-access

        view._toggle_sidebar()  # pylint: disable=protected-access
        view._toggle_sidebar()  # pylint: disable=protected-access

        assert_that(view._main_splitter.sizes()[0]).is_equal_to(actual_width)  # pylint: disable=protected-access


class TestSaveAndRestoreState:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_save_state_persists_splitter_sizes(self, qapp, tmp_path):  # pylint: disable=unused-argument
        store = UiStateStore(tmp_path / "config.db")
        view = DashboardView(ui_state_store=store)
        view._main_splitter.setSizes([300, 700])  # pylint: disable=protected-access
        view._content_splitter.setSizes([500, 200])  # pylint: disable=protected-access
        actual_main = view._main_splitter.sizes()  # pylint: disable=protected-access
        actual_content = view._content_splitter.sizes()  # pylint: disable=protected-access

        view.save_state()

        assert_that(store.get("splitter_main")).is_equal_to(actual_main)
        assert_that(store.get("splitter_content")).is_equal_to(actual_content)
        assert_that(store.get("sidebar_collapsed")).is_equal_to(0)

    def test_save_state_records_collapsed_sidebar(self, qapp, tmp_path):  # pylint: disable=unused-argument
        store = UiStateStore(tmp_path / "config.db")
        view = DashboardView(ui_state_store=store)
        view._collapse_sidebar()  # pylint: disable=protected-access

        view.save_state()

        assert_that(store.get("sidebar_collapsed")).is_equal_to(1)

    def test_restores_saved_splitter_sizes_on_construction(self, qapp, tmp_path):  # pylint: disable=unused-argument
        db_path = tmp_path / "config.db"
        UiStateStore(db_path).set("splitter_main", [333, 667])

        view = DashboardView(ui_state_store=UiStateStore(db_path))

        sizes = view._main_splitter.sizes()  # pylint: disable=protected-access
        assert_that(sizes[0]).is_greater_than(0)
        assert_that(sizes[0]).is_less_than(sizes[1])

    def test_restores_collapsed_sidebar_on_construction(self, qapp, tmp_path):  # pylint: disable=unused-argument
        db_path = tmp_path / "config.db"
        UiStateStore(db_path).set("sidebar_collapsed", 1)

        view = DashboardView(ui_state_store=UiStateStore(db_path))

        assert_that(view._main_splitter.sizes()[0]).is_equal_to(0)  # pylint: disable=protected-access


class TestDeviceSwitcher:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_selecting_device_updates_window_and_grid(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        mock_window = MagicMock()
        AppContext.get().window = mock_window
        view._devices = _DEVICES  # pylint: disable=protected-access

        view._on_device_selected(_D2)  # pylint: disable=protected-access

        mock_window.set_active_device.assert_called_once_with(_D2)
        assert_that(view._grid.key_count).is_equal_to(6)  # pylint: disable=protected-access


class TestViewMenu:  # pylint: disable=protected-access
    def setup_method(self):
        AppContext._instance = None

    def _menu(self, view: DashboardView):
        menu = view._page_tabs.menu
        view._page_tabs.menu_about_to_show.emit(menu)
        return menu

    def _action(self, menu, text: str):
        return next(a for a in menu.actions() if a.text() == text)

    def test_menu_lists_sidebar_device_settings(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        view._main_splitter.setSizes([200, 700])

        texts = [a.text() for a in self._menu(view).actions() if not a.isSeparator()]

        assert_that(texts).is_equal_to(["Hide Sidebar", "Device", "Settings"])

    def test_menu_button_is_right_of_tabs(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        bar = view._page_tabs
        layout = bar.layout()
        assert layout is not None

        assert_that(layout.indexOf(bar._menu_button)).is_equal_to(layout.count() - 1)
        assert_that(bar._menu_button.menu()).is_same_as(bar.menu)

    def test_sidebar_label_follows_state_and_toggles(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        view._main_splitter.setSizes([200, 700])

        self._action(self._menu(view), "Hide Sidebar").trigger()

        assert_that(view._is_sidebar_collapsed()).is_true()
        self._action(self._menu(view), "Show Sidebar").trigger()
        assert_that(view._is_sidebar_collapsed()).is_false()

    def test_reopening_does_not_duplicate_items(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        self._menu(view)

        assert_that(self._menu(view).actions()).is_length(4)

    def test_device_submenu_without_devices(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        submenu = self._action(self._menu(view), "Device").menu()

        assert_that([(a.text(), a.isEnabled()) for a in submenu.actions()]).is_equal_to(
            [("No devices connected", False)]
        )

    def test_device_submenu_checks_active_and_selects(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        mock_window = MagicMock()
        AppContext.get().window = mock_window
        AppContext.get().active_device = _D1
        view._devices = _DEVICES

        actions = self._action(self._menu(view), "Device").menu().actions()

        assert_that([a.isChecked() for a in actions]).is_equal_to([True, False])
        actions[1].trigger()
        mock_window.set_active_device.assert_called_with(_D2)
        assert_that(view._grid.key_count).is_equal_to(6)

    def test_settings_opens_settings_dialog(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        self._action(self._menu(view), "Settings").trigger()

        mock_window.open_settings.assert_called_once()


def _active_dev1(view: DashboardView) -> None:
    """Set active device to id='dev1' and build a 15-key grid."""
    AppContext.get().active_device = DeviceHardwareInfo(
        id="dev1", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15
    )
    view._grid.build(_KEYS_15)  # pylint: disable=protected-access
    view._pages = _PAGES  # pylint: disable=protected-access


class TestKeyDisplayStates:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_display_states_event_updates_key_labels(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)

        view.handle_event(
            KeyDisplayStatesUpdatedEvent(
                device_id="dev1",
                states=[
                    {
                        "key_index": 2,
                        "label": "42",
                        "plugin_uuid": "p",
                        "action_uuid": "a",
                        "context_id": "c",
                        "settings": {"step": 1},
                    }
                ],
            )
        )

        btn = view._grid._buttons.get(2)  # pylint: disable=protected-access
        assert btn is not None
        assert_that(btn.text()).is_equal_to("42")

    def test_display_states_event_ignored_for_different_device(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)

        view.handle_event(
            KeyDisplayStatesUpdatedEvent(
                device_id="other-dev",
                states=[
                    {
                        "key_index": 0,
                        "label": "99",
                        "plugin_uuid": "p",
                        "action_uuid": "a",
                        "context_id": "c",
                        "settings": {},
                    }
                ],
            )
        )
        btn = view._grid._buttons.get(0)  # pylint: disable=protected-access
        assert btn is not None
        assert_that(btn.text()).is_equal_to("1")  # default label unchanged

    def test_display_states_populates_key_slots(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)

        view.handle_event(
            KeyDisplayStatesUpdatedEvent(
                device_id="dev1",
                states=[
                    {
                        "key_index": 5,
                        "label": "7",
                        "plugin_uuid": "com.p",
                        "action_uuid": "com.p.a",
                        "context_id": "ctx1",
                        "settings": {"step": 2},
                    }
                ],
            )
        )
        assert_that(view._key_slots).contains_key(5)  # pylint: disable=protected-access
        assert_that(view._key_slots[5]["plugin_uuid"]).is_equal_to("com.p")  # pylint: disable=protected-access


class TestKeyInteractions:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_edit_requested_without_slot_shows_placeholder(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        view._grid.build(_KEYS_6)  # pylint: disable=protected-access
        view._on_key_edit_requested(0)  # pylint: disable=protected-access
        assert_that(view._config_panel.currentIndex()).is_equal_to(0)

    def test_key_press_with_slot_simulates_press(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[3] = {  # pylint: disable=protected-access
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }
        view._on_key_pressed(3)  # pylint: disable=protected-access
        mock_cm.call.assert_called_once_with("key_simulate_press", "dev1", 3)

    def test_pencil_selects_the_key_without_pressing(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[3] = {  # pylint: disable=protected-access
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }

        view._on_key_edit_requested(3)  # pylint: disable=protected-access

        assert_that(view._selected_key).is_equal_to(3)  # pylint: disable=protected-access
        pressed = [c for c in mock_cm.call.call_args_list if c.args and c.args[0] == "key_simulate_press"]
        assert_that(pressed).is_empty()

    def test_key_press_does_not_change_the_selection(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        AppContext.get().connection_manager = MagicMock()
        view._key_slots[3] = {"plugin_uuid": "p", "action_uuid": "a", "context_id": "c", "settings": {}}
        view._key_slots[4] = {"plugin_uuid": "p", "action_uuid": "a", "context_id": "d", "settings": {}}
        view._on_key_edit_requested(4)  # pylint: disable=protected-access

        view._on_key_pressed(3)  # pylint: disable=protected-access

        assert_that(view._selected_key).is_equal_to(4)  # pylint: disable=protected-access

    def test_key_press_without_a_slot_calls_nothing(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm

        view._on_key_pressed(2)  # pylint: disable=protected-access

        mock_cm.call.assert_not_called()

    def test_key_press_without_a_connection_does_not_raise(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        AppContext.get().connection_manager = None
        view._key_slots[3] = {
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }  # pylint: disable=protected-access

        view._on_key_pressed(3)  # pylint: disable=protected-access

    def test_long_press_simulates_a_long_press_and_does_not_select(  # pylint: disable=unused-argument
        self, qapp, tmp_path
    ):
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[3] = {
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }  # pylint: disable=protected-access

        view._on_key_long_pressed(3)  # pylint: disable=protected-access

        mock_cm.call.assert_called_once_with("key_simulate_long_press", "dev1", 3)
        assert_that(view._selected_key).is_none()  # pylint: disable=protected-access

    def test_grid_pencil_reaches_the_dashboard_and_key_click_presses(  # pylint: disable=unused-argument
        self, qapp, tmp_path
    ):
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[3] = {
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }  # pylint: disable=protected-access
        view._grid.build(_KEYS_6)  # pylint: disable=protected-access
        button = view._grid._buttons[3]  # pylint: disable=protected-access

        button._edit_button.click()  # pylint: disable=protected-access
        assert_that(view._selected_key).is_equal_to(3)  # pylint: disable=protected-access
        mock_cm.call.assert_not_called()

        button.click()
        mock_cm.call.assert_called_once_with("key_simulate_press", "dev1", 3)

    def test_key_long_pressed_simulates_long_press(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[1] = {
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }  # pylint: disable=protected-access
        view._on_key_long_pressed(1)  # pylint: disable=protected-access
        mock_cm.call.assert_called_once_with("key_simulate_long_press", "dev1", 1)

    def test_action_dropped_calls_key_assign_rpc(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        mock_cm.call.return_value = True
        AppContext.get().connection_manager = mock_cm
        view._on_action_dropped(
            4, {"plugin_uuid": "com.p", "action_uuid": "com.p.a"}
        )  # pylint: disable=protected-access
        assert_that(mock_cm.call.call_args[0][:4]).is_equal_to(("key_assign", "dev1", "p1", 4))
        assert_that(view._key_slots).contains_key(4)  # pylint: disable=protected-access

    def test_save_key_settings_calls_update_settings_rpc(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[2] = {
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }  # pylint: disable=protected-access
        view._save_key_settings(2, {"step": 5, "max": 10})  # pylint: disable=protected-access
        mock_cm.call.assert_called_once_with("key_update_settings", "dev1", "p1", 2, json.dumps({"step": 5, "max": 10}))

    def test_selecting_key_shows_schema_form_for_its_action(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        AppContext.get().connection_manager = MagicMock()
        schema: list[dict[str, Any]] = [
            {"key": "step", "type": "int", "label": "Step", "default": 1, "min": 1, "max": 9}
        ]
        view.handle_event(
            ActionListUpdatedEvent(
                actions=[
                    {"plugin_uuid": "com.p", "action_uuid": "com.p.a", "action_name": "A", "settings_schema": schema}
                ]
            )
        )
        view._key_slots[3] = {  # pylint: disable=protected-access
            "plugin_uuid": "com.p",
            "action_uuid": "com.p.a",
            "context_id": "c",
            "settings": {"step": 4},
        }

        view._on_key_edit_requested(3)  # pylint: disable=protected-access

        panel = view._config_panel  # pylint: disable=protected-access
        assert_that(panel.currentIndex()).is_equal_to(1)
        assert_that(panel._settings_form.values()).is_equal_to({"step": 4})  # pylint: disable=protected-access

    def test_selecting_another_key_with_identical_values_drops_unsaved_edits(  # pylint: disable=unused-argument
        self, qapp, tmp_path
    ):
        view = _make_view(tmp_path)
        _active_dev1(view)
        AppContext.get().connection_manager = MagicMock()
        schema: list[dict[str, Any]] = [
            {"key": "step", "type": "int", "label": "Step", "default": 1, "min": 1, "max": 9}
        ]
        view.handle_event(
            ActionListUpdatedEvent(
                actions=[
                    {"plugin_uuid": "com.p", "action_uuid": "com.p.a", "action_name": "A", "settings_schema": schema}
                ]
            )
        )
        for key in (3, 4):
            view._key_slots[key] = {  # pylint: disable=protected-access
                "plugin_uuid": "com.p",
                "action_uuid": "com.p.a",
                "context_id": f"c{key}",
                "settings": {"step": 2},
            }
        view._on_key_edit_requested(3)  # pylint: disable=protected-access
        panel = view._config_panel  # pylint: disable=protected-access
        panel._settings_form._fields["step"].set(8)  # pylint: disable=protected-access

        view._on_key_edit_requested(4)  # pylint: disable=protected-access

        assert_that(panel._settings_form.values()).is_equal_to({"step": 2})  # pylint: disable=protected-access

    def test_save_calls_key_update_settings_and_key_update_appearance(  # pylint: disable=unused-argument
        self, qapp, tmp_path
    ):
        view = _make_view(tmp_path)
        _active_dev1(view)
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[2] = {  # pylint: disable=protected-access
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
            "appearance": {"background": "#000000"},
            "appearance_defaults": {"background": "#000000"},
        }

        view._make_save_callback(2)({"step": 2}, {"background": "#ff0000"})  # pylint: disable=protected-access

        calls = [c.args for c in mock_cm.call.call_args_list]
        assert_that(calls).is_equal_to(
            [
                ("key_update_settings", "dev1", "p1", 2, json.dumps({"step": 2})),
                ("key_update_appearance", "dev1", "p1", 2, json.dumps({"background": "#ff0000"})),
            ]
        )


class TestPages:  # pylint: disable=protected-access
    def setup_method(self):
        AppContext._instance = None

    def _view(self, tmp_path) -> tuple[DashboardView, MagicMock]:
        view = _make_view(tmp_path)
        _active_dev1(view)
        view._pages = None
        cm = MagicMock()
        cm.call.return_value = True
        AppContext.get().connection_manager = cm
        view.handle_event(PagesUpdatedEvent(pages=_PAGES))
        cm.call.reset_mock()
        return view, cm

    def _tab_names(self, view: DashboardView) -> list[str]:
        tabs = view._page_tabs.tab_bar
        return [tabs.tabText(i) for i in range(tabs.count())]

    def test_pages_event_renders_tabs_with_active_and_default(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, _cm = self._view(tmp_path)

        view.handle_event(
            PagesUpdatedEvent(pages=dataclasses.replace(_PAGES, active_page_id="p2", default_page_id="p2"))
        )

        assert_that(self._tab_names(view)).is_equal_to(["Page 1", "Page 2"])
        assert_that(view._page_tabs.current_page_id).is_equal_to("p2")
        assert_that(view._active_page_id).is_equal_to("p2")

    def test_pages_for_other_device_are_ignored(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, _cm = self._view(tmp_path)

        view.handle_event(PagesUpdatedEvent(pages=dataclasses.replace(_PAGES, device_id="other", pages=[])))

        assert_that(self._tab_names(view)).is_equal_to(["Page 1", "Page 2"])

    def test_page_change_clears_key_selection(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, _cm = self._view(tmp_path)
        view._key_slots[0] = {"plugin_uuid": "p", "settings": {}}
        view._selected_key = 0

        view.handle_event(PagesUpdatedEvent(pages=dataclasses.replace(_PAGES, active_page_id="p2")))

        assert_that(view._key_slots).is_empty()
        assert_that(view._selected_key).is_none()

    def test_selecting_tab_activates_page_on_server(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)

        view._page_tabs.tab_bar.setCurrentIndex(1)

        cm.call.assert_called_once_with("page_activate", "dev1", "p2")

    def test_failed_activation_restores_selected_tab(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        cm.call.return_value = False

        view._page_tabs.tab_bar.setCurrentIndex(1)

        assert_that(view._page_tabs.current_page_id).is_equal_to("p1")

    def test_add_page_creates_then_activates_it(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        cm.call.side_effect = lambda method, *args: (
            json.dumps({"page_id": "p3", "name": "Page 3"}) if method == "page_add" else True
        )

        view._page_tabs.add_page_requested.emit()

        assert_that([c.args for c in cm.call.call_args_list]).is_equal_to(
            [("page_add", "dev1"), ("page_activate", "dev1", "p3")]
        )

    def test_add_page_failure_does_not_activate(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        cm.call.return_value = None

        view._page_tabs.add_page_requested.emit()

        cm.call.assert_called_once_with("page_add", "dev1")

    def test_delete_asks_first_and_deletes_on_yes(self, qapp, tmp_path, monkeypatch):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        asked: list[str] = []

        def _confirm(_parent, name):
            asked.append(name)
            return True

        monkeypatch.setattr("decker.client.views.dashboard._confirm_delete_page", _confirm)

        view._page_tabs.delete_page_requested.emit("p2")

        assert_that(asked).is_equal_to(["Page 2"])
        cm.call.assert_called_once_with("page_delete", "dev1", "p2")

    def test_delete_cancelled_does_nothing(self, qapp, tmp_path, monkeypatch):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        monkeypatch.setattr("decker.client.views.dashboard._confirm_delete_page", lambda *_: False)

        view._page_tabs.delete_page_requested.emit("p2")

        cm.call.assert_not_called()

    def test_confirm_dialog_maps_yes_and_cancel(self, qapp, tmp_path, monkeypatch):  # pylint: disable=unused-argument
        answers = iter([QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel])
        monkeypatch.setattr("decker.client.views.dashboard.QMessageBox.question", lambda *_args: next(answers))

        assert_that(_confirm_delete_page(_make_view(tmp_path), "Page 1")).is_true()
        assert_that(_confirm_delete_page(_make_view(tmp_path), "Page 1")).is_false()

    def test_rename_and_set_default_call_server(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)

        view._page_tabs.rename_page_requested.emit("p2", "Media")
        view._page_tabs.set_default_page_requested.emit("p2")

        assert_that([c.args for c in cm.call.call_args_list]).is_equal_to(
            [("page_rename", "dev1", "p2", "Media"), ("page_set_default", "dev1", "p2")]
        )

    def test_page_calls_need_device_and_connection(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        AppContext.get().connection_manager = None

        view._page_tabs.set_default_page_requested.emit("p2")

        cm.call.assert_not_called()

    def test_switching_device_clears_tabs_and_requests_refresh(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        view._active_device_id = "dev1"
        AppContext.get().window = MagicMock()

        view._on_device_selected(_D2)

        assert_that(view._page_tabs.tab_bar.count()).is_equal_to(0)
        cm.request_device_refresh.assert_called_once()

    def test_key_actions_need_known_page(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view, cm = self._view(tmp_path)
        view._pages = None

        view._on_action_dropped(0, {"plugin_uuid": "com.p", "action_uuid": "com.p.a"})
        view._save_key_settings(0, {})

        cm.call.assert_not_called()


class TestSlotSync:  # pylint: disable=protected-access
    def setup_method(self):
        AppContext._instance = None

    def test_full_state_tracks_assigned_and_drops_unassigned(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        view._key_slots[1] = {"plugin_uuid": "stale", "settings": {}}

        view.handle_event(
            KeyDisplayStatesUpdatedEvent(
                device_id="dev1",
                states=[
                    {"key_index": 0, "plugin_uuid": "com.p", "action_uuid": "a", "context_id": "c", "settings": {}},
                    {"key_index": 1, "plugin_uuid": None, "settings": {}},
                ],
            )
        )

        assert_that(view._key_slots).contains_key(0).does_not_contain_key(1)

    def test_partial_update_keeps_slot(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        _active_dev1(view)
        view._key_slots[0] = {"plugin_uuid": "com.p", "settings": {"step": 1}}

        view.handle_event(
            KeyDisplayStatesUpdatedEvent(device_id="dev1", states=[{"key_index": 0, "image_b64": None, "label": "7"}])
        )

        assert_that(view._key_slots[0]["settings"]).is_equal_to({"step": 1})
