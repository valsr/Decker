"""Base class and decorator for native Decker plugin actions."""

from abc import ABC
from collections.abc import Callable

from decker.plugin.context import ActionContext
from decker.plugin.gestures import Gesture


class DeckerPlugin(ABC):
    """Base class for a native plugin action. Override only the handlers you need."""

    action_uuid: str = ""

    def gestures(self, settings: dict) -> frozenset[Gesture]:  # pylint: disable=unused-argument
        """Gestures this instance wants, given its current settings; checked on every key press.

        Only register DOUBLE_PRESS when it is handled: it delays PRESS until the double-press window
        has passed. Unregistered LONG_PRESS means a long hold counts as a PRESS.
        """
        return frozenset({Gesture.PRESS})

    def on_key_down(self, ctx: ActionContext) -> None:
        """Called when the user presses the key this action is assigned to (raw event)."""

    def on_key_up(self, ctx: ActionContext) -> None:
        """Called when the user releases the key this action is assigned to (raw event)."""

    def on_press(self, ctx: ActionContext) -> None:
        """Called for a single press (see gestures)."""

    def on_double_press(self, ctx: ActionContext) -> None:
        """Called for a double press, if registered in gestures."""

    def on_long_press(self, ctx: ActionContext) -> None:
        """Called once the key has been held long enough, if registered in gestures."""

    def on_will_appear(self, ctx: ActionContext) -> None:
        """Called when this action instance is assigned to a key."""

    def on_will_disappear(self, ctx: ActionContext) -> None:
        """Called when this action instance is unassigned from a key."""

    def on_settings_changed(self, ctx: ActionContext) -> None:
        """Called when this action instance's settings are updated."""


def action(uuid: str) -> Callable[[type[DeckerPlugin]], type[DeckerPlugin]]:
    """Class decorator tagging a DeckerPlugin subclass with its manifest action UUID."""

    def decorator(cls: type[DeckerPlugin]) -> type[DeckerPlugin]:
        cls.action_uuid = uuid
        return cls

    return decorator
