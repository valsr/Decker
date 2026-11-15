"""Tests for decker.client.action_icons."""

import base64
from pathlib import Path

from assertpy import assert_that
from PyQt6.QtCore import Qt

from decker.client.action_icons import action_pixmap, decode_icon, placeholder_pixmap

_COUNTER_PNG = (
    Path(__file__).parents[2] / "src" / "decker" / "bundled_plugins" / "com.decker.counter" / "icons" / "counter.png"
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class TestDecodeIcon:
    def test_decodes_png(self, qapp):  # pylint: disable=unused-argument
        pixmap = decode_icon(_b64(_COUNTER_PNG.read_bytes()))

        assert pixmap is not None
        assert_that(pixmap.width()).is_greater_than(0)

    def test_decodes_svg(self, qapp):  # pylint: disable=unused-argument
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'

        assert_that(decode_icon(_b64(svg))).is_not_none()

    def test_empty_invalid_base64_or_non_image_is_none(self, qapp):  # pylint: disable=unused-argument
        assert_that(decode_icon("")).is_none()
        assert_that(decode_icon("not base64!")).is_none()
        assert_that(decode_icon(_b64(b"not an image"))).is_none()


class TestActionPixmap:
    def test_scales_icon_to_size(self, qapp):  # pylint: disable=unused-argument
        pixmap = action_pixmap({"action_name": "Counter", "icon_b64": _b64(_COUNTER_PNG.read_bytes())}, 32)

        assert_that((pixmap.width(), pixmap.height())).is_equal_to((32, 32))

    def test_falls_back_to_letter_tile(self, qapp):  # pylint: disable=unused-argument
        pixmap = action_pixmap({"action_name": "Open URL", "icon_b64": ""}, 40)

        assert_that(pixmap.toImage()).is_equal_to(placeholder_pixmap("Open URL", 40).toImage())


class TestPlaceholder:
    def test_same_name_same_tile_and_corners_transparent(self, qapp):  # pylint: disable=unused-argument
        first = placeholder_pixmap("Play", 48).toImage()

        assert_that(first).is_equal_to(placeholder_pixmap("Play", 48).toImage())
        assert_that(first.pixelColor(0, 0).alpha()).is_equal_to(0)
        assert_that(first.pixelColor(24, 4).alpha()).is_equal_to(255)

    def test_blank_name_still_renders(self, qapp):  # pylint: disable=unused-argument
        pixmap = placeholder_pixmap("  ", 16)

        assert_that(pixmap.isNull()).is_false()
        assert_that(pixmap.hasAlphaChannel()).is_true()
        assert_that(Qt.GlobalColor.transparent).is_not_none()
