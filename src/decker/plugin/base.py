"""Base class and decorator for native Decker plugin actions."""

from abc import ABC
from collections.abc import Callable

from decker.plugin.context import ActionContext


class DeckerPlugin(ABC):
    """Base class for a native plugin action. Override only the handlers you need."""

    action_uuid: str = ""

    def on_key_down(self, ctx: ActionContext) -> None:
        """Called when the user presses the key this action is assigned to."""

    def on_key_up(self, ctx: ActionContext) -> None:
        """Called when the user releases the key this action is assigned to."""

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
