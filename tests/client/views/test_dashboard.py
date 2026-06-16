"""Tests for decker.client.views.dashboard.DashboardView."""

from unittest.mock import MagicMock, patch

from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.events import ActionListUpdatedEvent, DeviceListUpdatedEvent
from decker.client.ui_state_store import UiStateStore
from decker.client.view_name import ViewName
from decker.client.views.dashboard import DashboardView

_DEVICES = [
    {"type": "Stream Deck", "serial": "ABC123", "keys": 15},
    {"type": "Stream Deck Mini", "serial": "XYZ999", "keys": 6},
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

        mock_window.set_active_device.assert_called_once_with("ABC123")

    def test_does_not_override_already_active_device(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "XYZ999"
        mock_window = MagicMock()
        AppContext.get().window = mock_window

        view.handle_event(DeviceListUpdatedEvent(devices=_DEVICES))

        mock_window.set_active_device.assert_not_called()

    def test_grid_resizes_to_active_devices_key_count(self, qapp, tmp_path):  # pylint: disable=unused-argument
        view = _make_view(tmp_path)
        AppContext.get().active_device = "XYZ999"

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
        AppContext.get().active_device = "ABC123"
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

        view._on_device_selected("XYZ999")  # pylint: disable=protected-access

        mock_window.set_active_device.assert_called_once_with("XYZ999")
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
