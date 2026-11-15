"""Gestures an action can register for."""

from enum import StrEnum


class Gesture(StrEnum):
    """A gesture an action can register for; dispatched to the matching on_<gesture> handler."""

    PRESS = "press"
    DOUBLE_PRESS = "double_press"
    LONG_PRESS = "long_press"
