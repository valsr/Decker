"""Tests for decker.client.views.device.DeviceView."""

from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.views.device import DeviceView
from decker.common.model import DeviceHardwareInfo, KeyInfo


class TestDeviceView:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_on_activate_shows_active_device_type(self, qapp):  # pylint: disable=unused-argument
        AppContext.get().active_device = DeviceHardwareInfo(
            id="abc123", type="Stream Deck XL", vendor_id=0, product_id=0, num_keys=32, serial="SN001"
        )
        view = DeviceView()

        view.on_activate()

        assert_that(view._title.text()).is_equal_to("Stream Deck XL")  # pylint: disable=protected-access

    def test_on_activate_shows_serial_and_id_in_info(self, qapp):  # pylint: disable=unused-argument
        AppContext.get().active_device = DeviceHardwareInfo(
            id="abc123", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15, serial="SN001"
        )
        view = DeviceView()

        view.on_activate()

        info = view._info.text()  # pylint: disable=protected-access
        assert_that(info).contains("SN001").contains("abc123")

    def test_on_activate_shows_key_layout_when_keys_provided(self, qapp):  # pylint: disable=unused-argument
        keys = [KeyInfo(row=r, col=c, pixel_width=72, pixel_height=72, type="key") for r in range(3) for c in range(5)]
        AppContext.get().active_device = DeviceHardwareInfo(
            id="abc123", type="Stream Deck", vendor_id=0, product_id=0, num_keys=15, keys=keys
        )
        view = DeviceView()

        view.on_activate()

        assert_that(view._info.text()).contains("3×5")  # pylint: disable=protected-access

    def test_on_activate_shows_placeholder_with_no_active_device(self, qapp):  # pylint: disable=unused-argument
        view = DeviceView()

        view.on_activate()

        assert_that(view._title.text()).is_equal_to("No device selected")  # pylint: disable=protected-access

    def test_icon_selected_updates_status_label(self, qapp):  # pylint: disable=unused-argument
        view = DeviceView()

        view._icon_picker.icon_selected.emit("/path/to/icon.svg")  # pylint: disable=protected-access

        assert_that(view._icon_status.text()).contains("/path/to/icon.svg")  # pylint: disable=protected-access

    def test_pack_icon_selected_updates_status_label(self, qapp):  # pylint: disable=unused-argument
        view = DeviceView()

        view._icon_picker.pack_icon_selected.emit("com.x/p", "a.svg")  # pylint: disable=protected-access

        assert_that(view._icon_status.text()).is_equal_to(
            "Selected: com.x/p / a.svg"
        )  # pylint: disable=protected-access
