import time

import pytest
from assertpy import assert_that

from decker.plugin.gestures import Gesture, GestureRecognizer

PRESS_ONLY = frozenset({Gesture.PRESS})
WITH_LONG = frozenset({Gesture.PRESS, Gesture.LONG_PRESS})
WITH_DOUBLE = frozenset({Gesture.PRESS, Gesture.DOUBLE_PRESS})
ALL = frozenset(Gesture)


class _FakeTimer:
    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback()


@pytest.fixture
def setup():
    fired: list[Gesture] = []
    timers: list[_FakeTimer] = []

    def factory(interval, callback):
        timer = _FakeTimer(interval, callback)
        timers.append(timer)
        return timer

    recognizer = GestureRecognizer(fired.append, long_press_s=0.5, double_press_s=0.35, timer_factory=factory)
    return recognizer, fired, timers


def _live(timers):
    return [t for t in timers if t.started and not t.cancelled]


class TestPressOnly:
    def test_press_fires_on_release_without_any_timer(self, setup):
        recognizer, fired, timers = setup

        recognizer.key_down(PRESS_ONLY)
        assert_that(fired).is_empty()
        recognizer.key_up()

        assert_that(fired).is_equal_to([Gesture.PRESS])
        assert_that(timers).is_empty()

    def test_quick_second_press_is_just_another_press(self, setup):
        recognizer, fired, _ = setup

        for _ in range(2):
            recognizer.key_down(PRESS_ONLY)
            recognizer.key_up()

        assert_that(fired).is_equal_to([Gesture.PRESS, Gesture.PRESS])

    def test_release_without_press_is_ignored(self, setup):
        recognizer, fired, _ = setup

        recognizer.key_up()

        assert_that(fired).is_empty()


class TestLongPress:
    def test_fires_while_held_and_release_adds_nothing(self, setup):
        recognizer, fired, timers = setup

        recognizer.key_down(WITH_LONG)
        assert_that(timers[0].interval).is_equal_to(0.5)
        timers[0].fire()
        assert_that(fired).is_equal_to([Gesture.LONG_PRESS])
        recognizer.key_up()

        assert_that(fired).is_equal_to([Gesture.LONG_PRESS])

    def test_short_press_cancels_hold_timer(self, setup):
        recognizer, fired, timers = setup

        recognizer.key_down(WITH_LONG)
        recognizer.key_up()

        assert_that(fired).is_equal_to([Gesture.PRESS])
        assert_that(timers[0].cancelled).is_true()

    def test_unregistered_long_hold_counts_as_press(self, setup):
        recognizer, fired, timers = setup

        recognizer.key_down(PRESS_ONLY)
        recognizer.key_up()

        assert_that(timers).is_empty()
        assert_that(fired).is_equal_to([Gesture.PRESS])

    def test_stale_hold_timer_is_ignored(self, setup):
        recognizer, fired, timers = setup
        recognizer.key_down(WITH_LONG)
        recognizer.key_up()
        recognizer.key_down(WITH_LONG)

        timers[0].fire()  # cancelled timer from the first press fires late

        assert_that(fired).is_equal_to([Gesture.PRESS])


class TestDoublePress:
    def test_single_press_waits_for_window(self, setup):
        recognizer, fired, timers = setup

        recognizer.key_down(WITH_DOUBLE)
        recognizer.key_up()
        assert_that(fired).is_empty()
        assert_that(timers[0].interval).is_equal_to(0.35)
        timers[0].fire()

        assert_that(fired).is_equal_to([Gesture.PRESS])

    def test_second_tap_in_window_is_double_press_only(self, setup):
        recognizer, fired, timers = setup

        recognizer.key_down(WITH_DOUBLE)
        recognizer.key_up()
        recognizer.key_down(WITH_DOUBLE)
        recognizer.key_up()

        assert_that(fired).is_equal_to([Gesture.DOUBLE_PRESS])
        assert_that(_live(timers)).is_empty()
        timers[0].fire()  # late firing of the cancelled window timer
        assert_that(fired).is_equal_to([Gesture.DOUBLE_PRESS])

    def test_third_tap_starts_a_new_gesture(self, setup):
        recognizer, fired, timers = setup

        for _ in range(3):
            recognizer.key_down(WITH_DOUBLE)
            recognizer.key_up()
        _live(timers)[0].fire()

        assert_that(fired).is_equal_to([Gesture.DOUBLE_PRESS, Gesture.PRESS])

    def test_holding_the_second_tap_gives_press_then_long_press(self, setup):
        recognizer, fired, timers = setup

        recognizer.key_down(ALL)
        recognizer.key_up()
        recognizer.key_down(ALL)
        _live(timers)[0].fire()  # hold timer of the second tap
        recognizer.key_up()

        assert_that(fired).is_equal_to([Gesture.PRESS, Gesture.LONG_PRESS])

    def test_gestures_not_registered_are_not_emitted(self, setup):
        recognizer, fired, _ = setup

        recognizer.key_down(frozenset({Gesture.DOUBLE_PRESS}))
        recognizer.key_up()
        recognizer.key_down(frozenset({Gesture.DOUBLE_PRESS}))
        recognizer.key_up()

        assert_that(fired).is_equal_to([Gesture.DOUBLE_PRESS])


class TestCancel:
    def test_cancel_drops_pending_gestures(self, setup):
        recognizer, fired, timers = setup
        recognizer.key_down(ALL)
        recognizer.key_up()

        recognizer.cancel()
        for timer in timers:
            timer.fire()

        assert_that(fired).is_empty()
        assert_that(_live(timers)).is_empty()


def test_real_timers_fire_press_after_window():
    fired: list[Gesture] = []
    recognizer = GestureRecognizer(fired.append, double_press_s=0.02)

    recognizer.key_down(WITH_DOUBLE)
    recognizer.key_up()
    deadline = time.monotonic() + 1
    while not fired and time.monotonic() < deadline:
        time.sleep(0.005)

    assert_that(fired).is_equal_to([Gesture.PRESS])
