"""Tests for decker.client.views.settings.SettingsView."""

from unittest.mock import patch

from assertpy import assert_that

from decker.client.views.settings import SettingsView


class TestSettingsView:
    def test_on_activate_loads_current_config_values(self, qapp):  # pylint: disable=unused-argument
        view = SettingsView()
        with (patch("decker.client.views.settings.config.get_as", side_effect=["myhost", 1234]),):
            view.on_activate()

        assert_that(view._host_input.text()).is_equal_to("myhost")  # pylint: disable=protected-access
        assert_that(view._port_input.text()).is_equal_to("1234")  # pylint: disable=protected-access

    def test_save_writes_host_and_port_to_config(self, qapp):  # pylint: disable=unused-argument
        view = SettingsView()
        view._host_input.setText("otherhost")  # pylint: disable=protected-access
        view._port_input.setText("9999")  # pylint: disable=protected-access

        with patch("decker.client.views.settings.config.set") as mock_set:
            view._on_save()  # pylint: disable=protected-access

        mock_set.assert_any_call("client.server_host", "otherhost")
        mock_set.assert_any_call("client.server_port", 9999)
        assert_that(view._saved_label.text()).is_equal_to("Saved.")  # pylint: disable=protected-access
        assert_that(view._saved_label.isHidden()).is_false()  # pylint: disable=protected-access
