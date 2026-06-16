"""Tests for decker.client.views.connecting.ConnectingView."""

from assertpy import assert_that

from decker.client.views.connecting import ConnectingView


class TestConnectingView:
    def test_on_activate_resets_attempt_counter_and_starts_timer(self, qapp):  # pylint: disable=unused-argument
        view = ConnectingView()
        view._attempts = 7  # pylint: disable=protected-access

        view.on_activate()

        assert_that(view._attempts).is_equal_to(0)  # pylint: disable=protected-access
        assert_that(view._tick_timer.isActive()).is_true()  # pylint: disable=protected-access

    def test_on_deactivate_stops_timer(self, qapp):  # pylint: disable=unused-argument
        view = ConnectingView()
        view.on_activate()

        view.on_deactivate()

        assert_that(view._tick_timer.isActive()).is_false()  # pylint: disable=protected-access

    def test_tick_increments_attempt_counter(self, qapp):  # pylint: disable=unused-argument
        view = ConnectingView()
        view.on_activate()

        view._on_tick()  # pylint: disable=protected-access

        assert_that(view._attempts).is_equal_to(1)  # pylint: disable=protected-access
