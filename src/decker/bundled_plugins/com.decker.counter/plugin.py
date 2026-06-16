"""Counter action — increments on press, resets on long press (>= 500 ms)."""

import io
import time

from PIL import Image, ImageDraw

from decker.plugin.base import DeckerPlugin, action
from decker.plugin.context import ActionContext

_LONG_PRESS_S = 0.5
_IMG_SIZE = 72
_BG_COLOR = (31, 97, 141)
_TEXT_COLOR = (255, 255, 255)


def _render_count(count: int) -> bytes:
    img = Image.new("RGB", (_IMG_SIZE, _IMG_SIZE), _BG_COLOR)
    draw = ImageDraw.Draw(img)
    try:
        from PIL import ImageFont  # pylint: disable=import-outside-toplevel

        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 28)
    except Exception:  # pylint: disable=broad-except
        from PIL import ImageFont  # pylint: disable=import-outside-toplevel

        font = ImageFont.load_default()
    draw.text((_IMG_SIZE // 2, _IMG_SIZE // 2), str(count), fill=_TEXT_COLOR, font=font, anchor="mm")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@action("com.decker.counter.counter")
class CounterAction(DeckerPlugin):
    """Counts presses. Short press increments; long press resets to 0."""

    def __init__(self) -> None:
        self._count: int = 0
        self._press_time: float = 0.0

    def on_will_appear(self, ctx: ActionContext) -> None:
        self._count = 0
        self._push(ctx)

    def on_key_down(self, ctx: ActionContext) -> None:
        self._press_time = time.monotonic()

    def on_key_up(self, ctx: ActionContext) -> None:
        elapsed = time.monotonic() - self._press_time
        settings = ctx.get_settings()
        if elapsed >= _LONG_PRESS_S:
            self._count = 0
        else:
            step = int(settings.get("step", 1))
            max_count = int(settings.get("max", 0))
            self._count += step
            if max_count > 0 and self._count >= max_count:
                self._count = 0
        self._push(ctx)

    def on_settings_changed(self, ctx: ActionContext) -> None:
        self._push(ctx)

    def _push(self, ctx: ActionContext) -> None:
        ctx.set_image(_render_count(self._count))
        ctx.set_title(str(self._count))
