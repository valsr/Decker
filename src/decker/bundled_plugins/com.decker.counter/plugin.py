"""Counter action: press adds step, double press adds double_step (if set), long press resets.

Settings (always complete: the server fills defaults from the manifest schema):
    step              int, added on press (default 1)
    double_step       int or empty, added on double press; empty means no double press, so presses
                      register immediately (default empty)
    max               int, wraps to 0 when reached; 0 = no limit (default 0)
    background        "#rrggbb" key background (default "#1f618d")
    title             text drawn on the key (default "")
    title_position    "top" | "middle" | "bottom" (default "bottom")
    title_font        font family name (default "DejaVu Sans")
    title_size        font size in px on a 72 px key (default 12)
    title_color       "#rrggbb" (default "#ffffff")
    title_outline     "#rrggbb" outline colour, None for none (default None)
    title_outline_width  outline width in px on a 72 px key (default 1)
"""

import functools
import io
import logging
import subprocess
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from decker_plugin_sdk import ActionContext, DeckerPlugin, Gesture, action

_KEY_SIZE = 72  # sizes in settings are relative to a 72 px key
_SCALE = 2  # render at 2x so the image stays sharp when scaled to larger keys
_COUNT_SIZE = 28
_COUNT_COLOR = "#ffffff"
_FALLBACK_FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
_TITLE_MARGIN = 4


@functools.lru_cache(maxsize=32)
def _font_file(family: str, bold: bool) -> str | None:
    """Resolve a font family to a file with fontconfig; None if it is unavailable."""
    pattern = f"{family}:style=Bold" if bold else family
    try:
        result = subprocess.run(
            ["fc-match", pattern, "--format=%{file}"], capture_output=True, text=True, timeout=2, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.debug("fc-match failed for %r: %s", family, exc)
        return None
    return result.stdout.strip() or None


def _font(family: str, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (_font_file(family, bold), _FALLBACK_FONT):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def render(count: int, settings: dict[str, Any]) -> bytes:
    """Render the key image: background, the count in the middle, and the optional title."""
    size = _KEY_SIZE * _SCALE
    img = Image.new("RGB", (size, size), settings["background"])
    draw = ImageDraw.Draw(img)
    centre = size // 2
    draw.text(
        (centre, centre),
        str(count),
        fill=_COUNT_COLOR,
        font=_font("DejaVu Sans", _COUNT_SIZE * _SCALE, True),
        anchor="mm",
    )
    title = str(settings["title"] or "")
    if title:
        _draw_title(draw, title, settings, size)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _draw_title(draw: ImageDraw.ImageDraw, title: str, settings: dict[str, Any], size: int) -> None:
    margin = _TITLE_MARGIN * _SCALE
    anchor, y = {"top": ("mt", margin), "middle": ("mm", size // 2), "bottom": ("mb", size - margin)}[
        settings["title_position"]
    ]
    outline_color = settings["title_outline"] or None
    outline_width = settings["title_outline_width"] * _SCALE if outline_color else 0
    draw.text(
        (size // 2, y),
        title,
        fill=settings["title_color"],
        font=_font(settings["title_font"] or "DejaVu Sans", settings["title_size"] * _SCALE),
        anchor=anchor,
        stroke_width=outline_width,
        stroke_fill=outline_color,
    )


@action("com.decker.counter.counter")
class CounterAction(DeckerPlugin):
    """Counts presses: press adds step, double press adds double_step, long press resets to 0."""

    def __init__(self) -> None:
        self._count: int = 0

    def gestures(self, settings: dict[str, Any]) -> frozenset[Gesture]:
        """Double press is only registered when double_step is set, so plain presses never wait for it."""
        wanted = {Gesture.PRESS, Gesture.LONG_PRESS}
        if settings.get("double_step") is not None:
            wanted.add(Gesture.DOUBLE_PRESS)
        return frozenset(wanted)

    def on_will_appear(self, ctx: ActionContext) -> None:
        self._count = 0
        self._push(ctx)

    def on_press(self, ctx: ActionContext) -> None:
        self._advance(ctx.settings["step"], ctx.settings["max"])
        self._push(ctx)

    def on_double_press(self, ctx: ActionContext) -> None:
        self._advance(ctx.settings["double_step"] or 0, ctx.settings["max"])
        self._push(ctx)

    def on_long_press(self, ctx: ActionContext) -> None:
        self._count = 0
        self._push(ctx)

    def on_settings_changed(self, ctx: ActionContext) -> None:
        self._push(ctx)

    def _advance(self, amount: int, max_count: int) -> None:
        self._count += amount
        if max_count > 0 and self._count >= max_count:
            self._count = 0

    def _push(self, ctx: ActionContext) -> None:
        ctx.set_image(render(self._count, ctx.settings))
        ctx.set_title(str(self._count))
