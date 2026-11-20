"""Gestures a card can register for."""

from enum import StrEnum


class Gesture(StrEnum):
    """A gesture a card can register for; dispatched to the matching on_<gesture> handler."""

    PRESS = "press"
    DOUBLE_PRESS = "double_press"
    LONG_PRESS = "long_press"
