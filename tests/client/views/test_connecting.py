"""Tests for decker.client.views.connecting.ReconnectWaitingOverlay."""

from unittest.mock import MagicMock, patch

from assertpy import assert_that
from PyQt6.QtWidgets import QWidget

from decker.client.views.connecting import ReconnectWaitingOverlay


def _make_overlay(qapp, parent: QWidget | None = None) -> ReconnectWaitingOverlay:  # pylint: disable=unused-argument
    return ReconnectWaitingOverlay(on_settings=MagicMock())


class TestConnectingOverlay:
    def test_on_activate_label_shows_configured_host_and_port(self, qapp):  # pylint: disable=unused-argument
        overlay = _make_overlay(qapp)
        with (
            patch("decker.client.config.get_server_host", return_value="localhost"),
            patch("decker.client.config.get_server_port", return_value=18861),
        ):
            overlay.on_activate()
        assert_that(overlay._label.text()).contains("localhost").contains("18861")  # pylint: disable=protected-access

    def test_initially_hidden(self, qapp):  # pylint: disable=unused-argument
        overlay = _make_overlay(qapp)
        assert_that(overlay.isHidden()).is_true()

    def test_on_deactivate_hides_overlay(self, qapp):  # pylint: disable=unused-argument
        overlay = _make_overlay(qapp)
        overlay.show()
        overlay.on_deactivate()
        assert_that(overlay.isHidden()).is_true()

    def test_on_deactivate_clears_blurred_background(self, qapp):  # pylint: disable=unused-argument
        overlay = _make_overlay(qapp)
        overlay._blurred_bg = MagicMock()  # pylint: disable=protected-access
        overlay.on_deactivate()
        assert_that(overlay._blurred_bg).is_none()  # pylint: disable=protected-access

    def test_on_activate_shows_overlay(self, qapp):  # pylint: disable=unused-argument
        parent = QWidget()
        parent.resize(400, 300)
        parent.show()
        overlay = ReconnectWaitingOverlay(on_settings=MagicMock())
        overlay.setParent(parent)
        overlay.on_activate()
        assert_that(overlay.isVisible()).is_true()

    def test_set_message_replaces_label_text(self, qapp):  # pylint: disable=unused-argument
        overlay = _make_overlay(qapp)
        overlay.set_message("hello")
        assert_that(overlay._label.text()).is_equal_to("hello")  # pylint: disable=protected-access

    def test_settings_button_calls_callback(self, qapp):  # pylint: disable=unused-argument
        callback = MagicMock()
        overlay = ReconnectWaitingOverlay(on_settings=callback)
        overlay._settings_btn.click()  # pylint: disable=protected-access
        callback.assert_called_once()
