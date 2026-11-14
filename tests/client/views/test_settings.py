"""Tests for decker.client.views.settings.SettingsView."""

from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.client.context import AppContext
from decker.client.views.settings import SettingsView


class TestSettingsView:
    def test_on_activate_loads_current_config_values(self, qapp):  # pylint: disable=unused-argument
        view = SettingsView()
        with (patch("decker.client.config.config.get_as", side_effect=["myhost", 1234]),):
            view.on_activate()

        assert_that(view._host_input.text()).is_equal_to("myhost")  # pylint: disable=protected-access
        assert_that(view._port_input.text()).is_equal_to("1234")  # pylint: disable=protected-access

    def test_save_writes_host_and_port_to_config(self, qapp):  # pylint: disable=unused-argument
        view = SettingsView()
        view._host_input.setText("otherhost")  # pylint: disable=protected-access
        view._port_input.setText("9999")  # pylint: disable=protected-access

        with patch("decker.client.config.config.set") as mock_set:
            view._on_save()  # pylint: disable=protected-access

        mock_set.assert_any_call("client.server_host", "otherhost")
        mock_set.assert_any_call("client.server_port", 9999)
        assert_that(view._saved_label.text()).is_equal_to("Saved.")  # pylint: disable=protected-access
        assert_that(view._saved_label.isHidden()).is_false()  # pylint: disable=protected-access

    def test_failed_plugins_placeholder_defaults_to_none(self, qapp):  # pylint: disable=unused-argument
        view = SettingsView()
        assert_that(view._failed_plugins_label.text()).is_equal_to("(none)")  # pylint: disable=protected-access

    @pytest.mark.parametrize("port", ["abc", "", "0", "65536", "-1"])
    def test_save_rejects_invalid_port_without_writing(self, qapp, port):  # pylint: disable=unused-argument
        view = SettingsView()
        view._host_input.setText("host")  # pylint: disable=protected-access
        view._port_input.setText(port)  # pylint: disable=protected-access

        with patch("decker.client.config.config.set") as mock_set:
            view._on_save()  # pylint: disable=protected-access

        mock_set.assert_not_called()
        assert_that(view._saved_label.text()).contains("65535")  # pylint: disable=protected-access

    def test_save_requests_reconnect(self, qapp):  # pylint: disable=unused-argument
        AppContext.reset()
        manager = MagicMock()
        AppContext.get().connection_manager = manager
        view = SettingsView()
        view._host_input.setText("otherhost")  # pylint: disable=protected-access
        view._port_input.setText("9999")  # pylint: disable=protected-access

        with patch("decker.client.config.config.set"):
            view._on_save()  # pylint: disable=protected-access

        manager.request_reconnect.assert_called_once()
        AppContext.reset()
