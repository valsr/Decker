"""Tests for the _KeyTracker gesture state machine."""

import time

import pytest
from assertpy import assert_that

from decker.common.model import KeyPressState
from decker.server.devices import _KeyTracker


class TestKeyTrackerBasic:
    def test_initial_state_is_up(self):
        tracker = _KeyTracker()
        assert_that(tracker.state).is_equal_to(KeyPressState.UP)

    def test_down_on_press(self):
        tracker = _KeyTracker()
        tracker.on_down()
        assert_that(tracker.state).is_equal_to(KeyPressState.DOWN)

    def test_up_after_quick_release(self):
        tracker = _KeyTracker()
        tracker.on_down()
        tracker.on_up()
        assert_that(tracker.state).is_equal_to(KeyPressState.UP)

    def test_held_after_timeout(self):
        from unittest.mock import patch  # pylint: disable=import-outside-toplevel

        tracker = _KeyTracker()
        fired = []

        with patch("decker.server.devices._HELD_THRESHOLD_S", 0.0):
            tracker.on_down()
            time.sleep(0.05)
            assert_that(tracker.state).is_equal_to(KeyPressState.HELD)

    def test_up_after_held_resets_to_up(self):
        tracker = _KeyTracker()
        with patch_held(tracker):
            tracker.on_up()
        assert_that(tracker.state).is_equal_to(KeyPressState.UP)


class TestKeyTrackerMultiTap:
    def test_double_press_within_window(self):
        tracker = _KeyTracker()
        tracker.on_down()
        tracker.on_up()
        tracker.on_down()
        tracker.on_up()
        assert_that(tracker.state).is_equal_to(KeyPressState.DOUBLE_PRESSED)

    def test_triple_press_within_window(self):
        tracker = _KeyTracker()
        for _ in range(3):
            tracker.on_down()
            tracker.on_up()
        assert_that(tracker.state).is_equal_to(KeyPressState.TRIPLE_PRESSED)

    def test_single_tap_outside_window_resets(self):
        from decker.server.devices import (
            _MULTI_TAP_WINDOW_S,  # pylint: disable=import-outside-toplevel
        )

        tracker = _KeyTracker()
        tracker.on_down()
        tracker.on_up()
        # Force last_up to be far in the past
        tracker._last_up = time.monotonic() - _MULTI_TAP_WINDOW_S - 0.1  # pylint: disable=protected-access
        tracker.on_down()
        tracker.on_up()
        # Should be a fresh single tap, state is UP
        assert_that(tracker.state).is_equal_to(KeyPressState.UP)


class TestKeyTrackerImageCache:
    def test_image_starts_none(self):
        tracker = _KeyTracker()
        assert_that(tracker.image).is_none()

    def test_image_can_be_set(self):
        tracker = _KeyTracker()
        tracker.image = b"png_data"
        assert_that(tracker.image).is_equal_to(b"png_data")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def patch_held(tracker: _KeyTracker):
    """Context manager that forces the tracker into HELD state."""

    class _Ctx:
        def __enter__(self):
            tracker.state = KeyPressState.HELD
            return self

        def __exit__(self, *_):
            pass

    return _Ctx()
