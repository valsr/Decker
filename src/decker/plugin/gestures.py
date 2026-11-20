"""Turn raw key down/up events into press, double-press and long-press gestures."""

import threading
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

LONG_PRESS_S = 0.5
DOUBLE_PRESS_WINDOW_S = 0.35


class Gesture(StrEnum):
    """A gesture a card can register for; dispatched to the matching on_<gesture> handler."""

    PRESS = "press"
    DOUBLE_PRESS = "double_press"
    LONG_PRESS = "long_press"


class _Timer(Protocol):
    def start(self) -> None:
        """Start counting down."""

    def cancel(self) -> None:
        """Stop the timer if it has not fired yet."""


TimerFactory = Callable[[float, Callable[[], None]], _Timer]


def _thread_timer(interval: float, callback: Callable[[], None]) -> _Timer:
    timer = threading.Timer(interval, callback)
    timer.daemon = True
    return timer


class GestureRecognizer:  # pylint: disable=too-many-instance-attributes
    """Gesture state machine for one key, waiting only for the gestures the card registered for.

    - PRESS fires on release, immediately unless DOUBLE_PRESS is registered, in which case it fires
      once the double-press window passes without a second tap.
    - DOUBLE_PRESS fires on the release of a second tap inside the window.
    - LONG_PRESS fires while the key is still held, once it has been held for long_press_s;
      the release that follows produces no PRESS. If it is not registered, a long hold is a PRESS.
    """

    def __init__(
        self,
        emit: Callable[[Gesture], None],
        long_press_s: float = LONG_PRESS_S,
        double_press_s: float = DOUBLE_PRESS_WINDOW_S,
        timer_factory: TimerFactory = _thread_timer,
    ) -> None:
        self._emit = emit
        self._long_press_s = long_press_s
        self._double_press_s = double_press_s
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._enabled: frozenset[Gesture] = frozenset({Gesture.PRESS})
        self._down = False
        self._long_fired = False
        self._second_tap = False
        self._hold_timer: _Timer | None = None
        self._tap_timer: _Timer | None = None

    def key_down(self, enabled: frozenset[Gesture]) -> None:
        """Handle a key press; enabled is the set of gestures the card wants right now."""
        with self._lock:
            self._enabled = enabled
            self._down = True
            self._long_fired = False
            self._cancel_hold()
            self._second_tap = self._tap_timer is not None
            self._cancel_tap()
            if Gesture.LONG_PRESS in enabled:
                self._hold_timer = self._start_timer(self._long_press_s, self._on_hold)

    def key_up(self) -> None:
        """Handle a key release."""
        fired: list[Gesture] = []
        with self._lock:
            if not self._down:
                return
            self._down = False
            self._cancel_hold()
            if self._long_fired:
                return
            if self._second_tap:
                self._second_tap = False
                fired.append(Gesture.DOUBLE_PRESS)
            elif Gesture.DOUBLE_PRESS in self._enabled:
                self._tap_timer = self._start_timer(self._double_press_s, self._on_tap_window_closed)
            else:
                fired.append(Gesture.PRESS)
        self._fire(fired)

    def cancel(self) -> None:
        """Drop any pending gesture (e.g. when the card is removed from the key)."""
        with self._lock:
            self._cancel_hold()
            self._cancel_tap()
            self._down = False
            self._second_tap = False

    def _start_timer(self, interval: float, callback: Callable[[_Timer], None]) -> _Timer:
        # The callback gets its own timer so a late firing of a cancelled timer can be ignored.
        holder: list[_Timer] = []
        timer = self._timer_factory(interval, lambda: callback(holder[0]))
        holder.append(timer)
        timer.start()
        return timer

    def _on_hold(self, timer: _Timer) -> None:
        fired: list[Gesture] = []
        with self._lock:
            if not self._down or self._hold_timer is not timer:
                return
            self._hold_timer = None
            self._long_fired = True
            if self._second_tap:  # the first tap of an abandoned double press still counts
                self._second_tap = False
                fired.append(Gesture.PRESS)
            fired.append(Gesture.LONG_PRESS)
        self._fire(fired)

    def _on_tap_window_closed(self, timer: _Timer) -> None:
        with self._lock:
            if self._tap_timer is not timer:
                return
            self._tap_timer = None
        self._fire([Gesture.PRESS])

    def _fire(self, gestures: list[Gesture]) -> None:
        for gesture in gestures:
            if gesture in self._enabled:
                self._emit(gesture)

    def _cancel_hold(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _cancel_tap(self) -> None:
        if self._tap_timer is not None:
            self._tap_timer.cancel()
            self._tap_timer = None
