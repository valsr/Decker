"""Tests for decker.client.widgets.key_preview."""

# pylint: disable=protected-access,unused-argument
import base64
import io

from assertpy import assert_that
from PIL import Image
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QMenu

from decker.client.widgets.key_preview import KeyPreview


def _png_b64() -> str:
    buffer = io.BytesIO()
    Image.new("RGBA", (72, 72), "#ff0000").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _action(menu: QMenu, text: str):
    return next(a for a in menu.actions() if a.text() == text)


def test_image_is_shown_and_cleared(qapp) -> None:
    preview = KeyPreview()

    preview.set_image(_png_b64())
    pixmap = preview.pixmap()
    assert pixmap is not None and not pixmap.isNull()

    preview.set_image(None)
    pixmap = preview.pixmap()
    assert pixmap is None or pixmap.isNull()


def test_undecodable_image_is_treated_as_none(qapp) -> None:
    preview = KeyPreview()
    preview.set_image(_png_b64())

    preview.set_image("not base64 png")

    pixmap = preview.pixmap()
    assert pixmap is None or pixmap.isNull()


def test_double_click_requests_the_icon_picker(qapp) -> None:
    preview = KeyPreview()
    seen: list[bool] = []
    preview.set_icon_requested.connect(lambda: seen.append(True))
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick,
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    preview.mouseDoubleClickEvent(event)

    assert_that(seen).is_equal_to([True])


def test_menu_actions_emit_their_signals(qapp) -> None:
    preview = KeyPreview()
    preview.set_has_icon(True)
    seen: list[str] = []
    preview.set_icon_requested.connect(lambda: seen.append("set"))
    preview.clear_icon_requested.connect(lambda: seen.append("clear"))
    menu = preview._build_menu()

    _action(menu, "Set icon…").trigger()
    _action(menu, "Clear icon").trigger()

    assert_that(seen).is_equal_to(["set", "clear"])


def test_clear_is_disabled_without_an_icon(qapp) -> None:
    preview = KeyPreview()
    preview.set_has_icon(False)
    assert_that(_action(preview._build_menu(), "Clear icon").isEnabled()).is_false()
    preview.set_has_icon(True)
    assert_that(_action(preview._build_menu(), "Clear icon").isEnabled()).is_true()
