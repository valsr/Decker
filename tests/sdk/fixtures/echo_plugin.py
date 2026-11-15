"""Fixture plugin used by the SDK tests."""

import threading
import time

from decker_plugin_sdk import ActionContext, DeckerPlugin, Gesture, action

BLOCK = threading.Event()
SEEN: list[str] = []


@action("test.echo.echo")
class Echo(DeckerPlugin):
    def on_press(self, ctx: ActionContext) -> None:
        mode = ctx.settings.get("mode")
        if mode == "block":
            BLOCK.wait(5)
        elif mode == "boom":
            raise RuntimeError("boom")
        elif mode == "slow":
            time.sleep(0.2)
        SEEN.append(str(ctx.settings.get("tag", "")))
        ctx.set_title("pressed")

    def on_long_press(self, ctx: ActionContext) -> None:
        ctx.set_title("long")

    def gestures(self, settings: dict) -> frozenset[Gesture] | None:
        if settings.get("dbl"):
            return frozenset({Gesture.PRESS, Gesture.DOUBLE_PRESS})
        return None
