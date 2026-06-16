"""Tests for decker.client.views.device.DeviceView."""

from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.views.device import DeviceView


class TestDeviceView:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_on_activate_shows_active_device(self, qapp):  # pylint: disable=unused-argument
        AppContext.get().active_device = "abc123"
        view = DeviceView()

        view.on_activate()

        assert_that(view._title.text()).contains("abc123")  # pylint: disable=protected-access

    def test_on_activate_shows_placeholder_with_no_active_device(self, qapp):  # pylint: disable=unused-argument
        view = DeviceView()

        view.on_activate()

        assert_that(view._title.text()).is_equal_to("No device selected")  # pylint: disable=protected-access

    def test_icon_selected_updates_status_label(self, qapp):  # pylint: disable=unused-argument
        view = DeviceView()

        view._icon_picker.icon_selected.emit("/path/to/icon.svg")  # pylint: disable=protected-access

        assert_that(view._icon_status.text()).contains("/path/to/icon.svg")  # pylint: disable=protected-access
