"""Decker-drawn key appearance: resolves appearance settings and composes the final key image."""

import functools
import io
import logging
import subprocess
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from decker.asset.renderer import AssetRenderer
from decker.common.appearance_schema import APPEARANCE_SCHEMA
from decker.common.text_style import fold_legacy_title
from decker.plugin.settings_schema import apply_schema, parse_settings_schema

_BASE_SIZE = 72  # title sizes in settings are relative to a 72 px key
_FALLBACK_FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
_TITLE_MARGIN = 4
_PARSED_SCHEMA = parse_settings_schema(APPEARANCE_SCHEMA, "appearance")
_RENDERER = AssetRenderer()


@functools.lru_cache(maxsize=32)
def _font_file(family: str) -> str | None:
    """Resolve a font family to a file with fontconfig; None if it is unavailable."""
    try:
        result = subprocess.run(
            ["fc-match", family, "--format=%{file}"], capture_output=True, text=True, timeout=2, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.debug("fc-match failed for %r: %s", family, exc)
        return None
    return result.stdout.strip() or None


def _font(family: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (_font_file(family), _FALLBACK_FONT):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def resolve_appearance(action_defaults: Mapping[str, Any], stored: Mapping[str, Any]) -> dict[str, Any]:
    """Complete, typed appearance: schema defaults < action defaults < stored values (title merged per field)."""
    defaults = fold_legacy_title(action_defaults)
    values = fold_legacy_title(stored)
    merged = {**defaults, **values}
    if "title" in merged:
        merged["title"] = {**defaults.get("title", {}), **values.get("title", {})}
    return apply_schema(_PARSED_SCHEMA, merged)


def _draw_title(draw: ImageDraw.ImageDraw, text: str, style: Mapping[str, Any], size: int) -> None:
    scale = size / _BASE_SIZE
    margin = round(_TITLE_MARGIN * scale)
    anchor, y = {"top": ("mt", margin), "middle": ("mm", size // 2), "bottom": ("mb", size - margin)}[
        style["position"]
    ]
    outline = style["outline"] or None
    draw.text(
        (size // 2, y),
        text,
        fill=style["color"],
        font=_font(style["font"] or "DejaVu Sans", max(1, round(style["size"] * scale))),
        anchor=anchor,
        stroke_width=round(style["outline_width"] * scale) if outline else 0,
        stroke_fill=outline,
    )


def compose_key_image(
    appearance: Mapping[str, Any], plugin_image: bytes | None, plugin_title: str, size: int = 144
) -> bytes:
    """Compose background, plugin image and title into a size x size PNG."""
    img = Image.new("RGBA", (size, size), appearance["background"])
    if plugin_image:
        try:
            layer = _RENDERER.render_bytes(plugin_image, size, size)
            if layer is not None:
                img.alpha_composite(layer)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logging.debug("skipping unreadable plugin image: %s", exc)
    style = appearance["title"]
    text = style["text"] or plugin_title
    if style["visible"] and text:
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        _draw_title(ImageDraw.Draw(layer), text, style, size)
        img.alpha_composite(layer)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
