"""Decker-drawn key appearance: resolves appearance settings and composes the final key image."""

import functools
import io
import logging
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

from decker.asset.renderer import AssetRenderer
from decker.common.appearance_schema import APPEARANCE_SCHEMA
from decker.common.text_style import fold_legacy_title
from decker.plugin.settings_schema import apply_schema, parse_settings_schema

_BASE_SIZE = 72  # title sizes in settings are relative to a 72 px key
_FALLBACK_FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
_TITLE_MARGIN = 4
PACK_ICON_SCALE = 0.7  # pack icons are drawn at this fraction of the key, centred, so a title stays readable
_MIN_IMAGE_SCALE = 0.1
_LINE_BREAKS = re.compile(r"\s*[\r\n\v\f\x85\u2028\u2029]+\s*")
_BOLD_WEIGHT = 180  # fontconfig weight at or above which a face counts as really bold (FC_WEIGHT_BOLD is 200)
_PARSED_SCHEMA = parse_settings_schema(APPEARANCE_SCHEMA, "appearance")
_RENDERER = AssetRenderer()


@functools.lru_cache(maxsize=64)
def _font_file(family: str, bold: bool = False, italic: bool = False) -> tuple[str | None, bool]:
    """Resolve a family (and style) to ``(file, is_really_bold)`` with fontconfig; the file is None if unavailable."""
    pattern = family + (":bold" if bold else "") + (":italic" if italic else "")
    try:
        result = subprocess.run(
            ["fc-match", pattern, "--format=%{file}\n%{weight}"], capture_output=True, text=True, timeout=2, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.debug("fc-match failed for %r: %s", pattern, exc)
        return None, False
    path, _, weight = result.stdout.partition("\n")
    return (path.strip() or None), weight.strip().isdigit() and int(weight) >= _BOLD_WEIGHT


def _font(
    family: str, size: int, bold: bool = False, italic: bool = False
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """The font and whether it is really bold (so the caller knows when to fake it)."""
    path, real_bold = _font_file(family, bold, italic)
    for candidate, is_bold in ((path, real_bold), (_FALLBACK_FONT, True)):
        if candidate:
            try:
                return ImageFont.truetype(candidate, size), is_bold
            except OSError:
                continue
    return ImageFont.load_default(size), False


def resolve_appearance(action_defaults: Mapping[str, Any], stored: Mapping[str, Any]) -> dict[str, Any]:
    """Complete, typed appearance: schema defaults < action defaults < stored values (title merged per field)."""
    defaults = fold_legacy_title(action_defaults)
    values = fold_legacy_title(stored)
    merged = {**defaults, **values}
    if "title" in merged:
        merged["title"] = {**defaults.get("title", {}), **values.get("title", {})}
    return apply_schema(_PARSED_SCHEMA, merged)


@dataclass(frozen=True)
class _TitleDraw:
    text: str
    xy: tuple[int, int]
    anchor: str
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    color: str
    outline: str | None
    outline_width: int
    fake_bold: int


def _draw_text_passes(draw: ImageDraw.ImageDraw, t: _TitleDraw) -> None:
    if t.outline:
        draw.text(
            t.xy,
            t.text,
            fill=t.outline,
            font=t.font,
            anchor=t.anchor,
            stroke_width=t.outline_width + t.fake_bold,
            stroke_fill=t.outline,
        )
    draw.text(t.xy, t.text, fill=t.color, font=t.font, anchor=t.anchor, stroke_width=t.fake_bold, stroke_fill=t.color)


def _decoration_rects(
    draw: ImageDraw.ImageDraw, t: _TitleDraw, px: int, style: Mapping[str, Any]
) -> list[tuple[float, float, float, float]]:
    """Underline / strike rectangles (left, top, right, bottom) derived from the measured text box."""
    left, top, right, _ = draw.textbbox(t.xy, t.text, font=t.font, anchor=t.anchor, stroke_width=t.fake_bold)
    baseline = top - t.font.getbbox(t.text, anchor="ls")[1]
    thickness = max(1, round(px / 14))
    rects = []
    if style["underline"]:
        rects.append((left, baseline + thickness, right, baseline + 2 * thickness - 1))
    if style["strike"]:
        middle = baseline - round(px * 0.3)
        rects.append((left, middle - thickness // 2, right, middle - thickness // 2 + thickness - 1))
    return rects


def _title_draw(text: str, style: Mapping[str, Any], size: int) -> tuple[_TitleDraw, int]:
    """Resolve the style into what to draw, plus the font size in px."""
    scale = size / _BASE_SIZE
    margin = round(_TITLE_MARGIN * scale)
    anchor, y = {"top": ("mt", margin), "middle": ("mm", size // 2), "bottom": ("mb", size - margin)}[style["position"]]
    px = max(1, round(style["size"] * scale))
    font, real_bold = _font(style["font"] or "DejaVu Sans", px, style["bold"], style["italic"])
    outline = style["outline"] or None
    return (
        _TitleDraw(
            text=text,
            xy=(size // 2, y),
            anchor=anchor,
            font=font,
            color=style["color"],
            outline=outline,
            outline_width=round(style["outline_width"] * scale) if outline else 0,
            fake_bold=max(1, round(px / 24)) if style["bold"] and not real_bold else 0,
        ),
        px,
    )


def _draw_title(draw: ImageDraw.ImageDraw, text: str, style: Mapping[str, Any], size: int) -> None:
    title, px = _title_draw(text, style, size)
    rects = _decoration_rects(draw, title, px, style)
    if title.outline:
        grow = title.outline_width
        for left, top, right, bottom in rects:
            draw.rectangle((left - grow, top - grow, right + grow, bottom + grow), fill=title.outline)
    _draw_text_passes(draw, title)
    for rect in rects:
        draw.rectangle(rect, fill=title.color)


def _single_line(text: str) -> str:
    """Titles are one line (Pillow can't anchor multi-line text at the top or bottom): breaks become one space."""
    return _LINE_BREAKS.sub(" ", text)


def _background_layer(appearance: Mapping[str, Any], size: int) -> Image.Image:
    """Opaque black with the appearance background composited on top (the hardware has no transparency)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    if ImageColor.getcolor(appearance["background"], "RGBA")[3]:  # type: ignore[index]
        img.alpha_composite(Image.new("RGBA", (size, size), appearance["background"]))
    return img


def _inner_size(size: int, plugin_image_scale: float) -> int:
    return max(1, round(size * min(1.0, max(_MIN_IMAGE_SCALE, plugin_image_scale))))


def _title_layer(appearance: Mapping[str, Any], plugin_title: str, size: int) -> Image.Image | None:
    """The transparent title layer, or None when no title is shown."""
    style = appearance["title"]
    text = _single_line(style["text"] or plugin_title)
    if not (style["visible"] and text.strip()):
        return None
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _draw_title(ImageDraw.Draw(layer), text, style, size)
    return layer


def compose_key_image(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    appearance: Mapping[str, Any],
    plugin_image: bytes | None,
    plugin_title: str,
    size: int = 144,
    plugin_image_color: str | None = None,
    plugin_image_scale: float = 1.0,
) -> bytes:
    """Compose background, plugin image and title into a size x size PNG."""
    img = _background_layer(appearance, size)
    if plugin_image:
        try:
            inner = _inner_size(size, plugin_image_scale)
            layer = _RENDERER.render_bytes(plugin_image, inner, inner, plugin_image_color)
            if layer is not None:
                offset = (size - inner) // 2
                img.alpha_composite(layer, dest=(offset, offset))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.debug("skipping unreadable plugin image: %s", exc)
    title = _title_layer(appearance, plugin_title, size)
    if title is not None:
        img.alpha_composite(title)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def compose_key_frames(
    appearance: Mapping[str, Any],
    frames: Sequence[Image.Image],
    plugin_title: str,
    size: int = 144,
    plugin_image_scale: float = 1.0,
) -> list[Image.Image]:
    """Compose background, each animation frame and the title into size x size RGB images."""
    inner = _inner_size(size, plugin_image_scale)
    offset = (size - inner) // 2
    background = _background_layer(appearance, size)
    title = _title_layer(appearance, plugin_title, size)
    composed = []
    for frame in frames:
        img = background.copy()
        layer = frame.convert("RGBA").resize((inner, inner), Image.Resampling.LANCZOS)
        img.alpha_composite(layer, dest=(offset, offset))
        if title is not None:
            img.alpha_composite(title)
        composed.append(img.convert("RGB"))
    return composed
