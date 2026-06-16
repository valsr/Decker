"""Tests for decker.client.tray.TrayIcon."""

from unittest.mock import MagicMock, patch

from assertpy import assert_that
from PyQt6.QtWidgets import QSystemTrayIcon

from decker.client.tray import TrayIcon


def _make_window(visible: bool = True) -> MagicMock:
    window = MagicMock()
    window.isVisible.return_value = visible
    return window


class TestMenu:
    def test_menu_has_toggle_and_exit_actions(self, qapp):  # pylint: disable=unused-argument
        tray = TrayIcon(_make_window())
        labels = [action.text() for action in tray._menu.actions()]  # pylint: disable=protected-access
        assert_that(labels).is_equal_to(["Hide", "Exit"])

    def test_toggle_label_reflects_visible_window(self, qapp):  # pylint: disable=unused-argument
        tray = TrayIcon(_make_window(visible=True))
        tray._update_toggle_label()  # pylint: disable=protected-access
        assert_that(tray._toggle_action.text()).is_equal_to("Hide")  # pylint: disable=protected-access

    def test_toggle_label_reflects_hidden_window(self, qapp):  # pylint: disable=unused-argument
        tray = TrayIcon(_make_window(visible=False))
        tray._update_toggle_label()  # pylint: disable=protected-access
        assert_that(tray._toggle_action.text()).is_equal_to("Show")  # pylint: disable=protected-access


class TestToggleWindowVisibility:
    def test_hides_visible_window(self, qapp):  # pylint: disable=unused-argument
        window = _make_window(visible=True)
        tray = TrayIcon(window)
        tray._toggle_window_visibility()  # pylint: disable=protected-access
        window.hide.assert_called_once()
        window.show.assert_not_called()

    def test_shows_and_raises_hidden_window(self, qapp):  # pylint: disable=unused-argument
        window = _make_window(visible=False)
        tray = TrayIcon(window)
        tray._toggle_window_visibility()  # pylint: disable=protected-access
        window.show.assert_called_once()
        window.raise_.assert_called_once()
        window.activateWindow.assert_called_once()
        window.hide.assert_not_called()


class TestActivated:
    def test_trigger_toggles_visibility(self, qapp):  # pylint: disable=unused-argument
        window = _make_window(visible=True)
        tray = TrayIcon(window)
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)  # pylint: disable=protected-access
        window.hide.assert_called_once()

    def test_other_reasons_do_nothing(self, qapp):  # pylint: disable=unused-argument
        window = _make_window(visible=True)
        tray = TrayIcon(window)
        tray._on_activated(QSystemTrayIcon.ActivationReason.Context)  # pylint: disable=protected-access
        window.hide.assert_not_called()
        window.show.assert_not_called()


class TestExit:
    def test_exit_action_quits_application(self, qapp):  # pylint: disable=unused-argument
        tray = TrayIcon(_make_window())
        with patch("decker.client.tray.QApplication.quit") as mock_quit:
            tray._exit_app()  # pylint: disable=protected-access
        mock_quit.assert_called_once()
