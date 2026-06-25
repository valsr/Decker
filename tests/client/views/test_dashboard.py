"""Tests for decker.client.views.dashboard.DashboardView."""

from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.events import (
    ActionListUpdatedEvent,
    DeviceListUpdatedEvent,
    KeyDisplayStatesUpdatedEvent,
)
from decker.client.ui_state_store import UiStateStore
from decker.client.view_name import ViewName
from decker.client.views.dashboard import DashboardView

_DEVICES = [
    {"id": "aabbccdd", "type": "Stream Deck", "serial": "ABC123", "num_keys": 15, "keys": []},
    {"id": "11223344", "type": "Stream Deck Mini", "serial": "XYZ999", "num_keys": 6, "keys": []},
]


def _make_view(tmp_path) -> DashboardView:
    return DashboardView(ui_state_store=UiStateStore(tmp_path / "config.db"))


class TestDashboardView:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_constructs_with_two_pages_and_default_key_count(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        assert_that(view._pill_bar.button_group.buttons()).is_length(2)  # pylint: disable=protected-access
        assert_that(view._grid.key_count).is_equal_to(15)  # pylint: disable=protected-access


class TestDeviceListHandling:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_auto_selects_first_device_when_none_active(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        mock_window.set_active_device.assert_called_once_with("aabbccdd")

    def test_does_not_override_already_active_device(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "11223344"
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        mock_window.set_active_device.assert_not_called()

    def test_grid_resizes_to_active_devices_key_count(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "11223344"

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        assert_that(view._grid.key_count).is_equal_to(6)  # pylint: disable=protected-access

    def test_unknown_active_device_falls_back_to_default_key_count(
        self, qapp, tmp_path
    ):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "does-not-exist"

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        assert_that(view._grid.key_count).is_equal_to(15)  # pylint: disable=protected-access

    def test_same_device_does_not_rebuild_grid(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "aabbccdd"
        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        with patch.object(view._grid, "set_key_count") as mock_set:  # pylint: disable=protected-access
            view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))
            mock_set.assert_not_called()


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
        # Qt may adjust sizes to fit the widget's actual pixel budget in headless mode
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

        # Qt scales saved pixel values to the widget's actual budget; verify the
        # proportional split (33/67) was applied: first pane > 0 and smaller than second.
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

        view._on_device_selected("11223344")  # pylint: disable=protected-access

        mock_window.set_active_device.assert_called_once_with("11223344")
        assert_that(view._grid.key_count).is_equal_to(6)  # pylint: disable=protected-access


class TestSettingsButton:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_settings_clicked_switches_to_settings_view(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view._sidebar.settings_clicked.emit()  # pylint: disable=protected-access

        mock_window.switch_to.assert_called_once_with(ViewName.SETTINGS)


class TestKeyDisplayStates:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_display_states_event_updates_key_labels(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "dev1"
        view._grid.set_key_count(15)  # pylint: disable=protected-access

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
        AppContext.get().active_device = "dev1"
        view._grid.set_key_count(15)  # pylint: disable=protected-access
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
        AppContext.get().active_device = "dev1"
        view._grid.set_key_count(15)  # pylint: disable=protected-access
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

    def test_key_selected_without_slot_shows_placeholder(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        view._grid.set_key_count(6)  # pylint: disable=protected-access
        view._on_key_selected(0)  # pylint: disable=protected-access
        assert_that(view._config_panel.currentIndex()).is_equal_to(0)

    def test_key_selected_with_slot_simulates_press(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "dev1"
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[3] = {
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }  # pylint: disable=protected-access
        view._grid.set_key_count(15)  # pylint: disable=protected-access
        view._on_key_selected(3)  # pylint: disable=protected-access
        mock_cm.call.assert_called_once_with("key_simulate_press", "dev1", 3)

    def test_key_long_pressed_simulates_long_press(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "dev1"
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
        AppContext.get().active_device = "dev1"
        mock_cm = MagicMock()
        mock_cm.call.return_value = True
        AppContext.get().connection_manager = mock_cm
        view._grid.set_key_count(15)  # pylint: disable=protected-access
        view._on_action_dropped(
            4, {"plugin_uuid": "com.p", "action_uuid": "com.p.a"}
        )  # pylint: disable=protected-access
        assert_that(mock_cm.call.call_args[0][0]).is_equal_to("key_assign")
        assert_that(view._key_slots).contains_key(4)  # pylint: disable=protected-access

    def test_save_key_settings_calls_update_settings_rpc(self, qapp, tmp_path):  # pylint: disable=unused-argument
        import json

        view = _make_view(tmp_path)
        AppContext.get().active_device = "dev1"
        mock_cm = MagicMock()
        AppContext.get().connection_manager = mock_cm
        view._key_slots[2] = {
            "plugin_uuid": "p",
            "action_uuid": "a",
            "context_id": "c",
            "settings": {},
        }  # pylint: disable=protected-access
        view._save_key_settings(2, {"step": 5, "max": 10})  # pylint: disable=protected-access
        mock_cm.call.assert_called_once_with("key_update_settings", "dev1", 2, json.dumps({"step": 5, "max": 10}))
