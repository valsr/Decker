"""Tests for decker.client.widgets.icon_edit."""

# pylint: disable=protected-access,unused-argument
import base64
from typing import Any

from assertpy import assert_that
from PyQt6.QtCore import QObject, pyqtSignal

from decker.client.widgets.icon_edit import IconEdit

_CURRENT = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path fill="currentColor" d="M0 0h10v10H0z"/></svg>'
)
_REF = "pack:com.x.p/house.svg"


class FakeRpc:
    def __init__(self, svg: bytes | None = _CURRENT) -> None:
        self.svg = svg
        self.calls: list[tuple[Any, ...]] = []

    def call(self, method: str, *args: Any) -> str | None:
        self.calls.append((method, *args))
        if method == "iconpack_icon" and self.svg is not None:
            return base64.b64encode(self.svg).decode()
        return None


def _edit(rpc: FakeRpc | None = None) -> IconEdit:
    fake = rpc if rpc is not None else FakeRpc()
    return IconEdit(lambda: fake)  # type: ignore[arg-type,return-value]


def _centre(edit: IconEdit) -> tuple[int, int, int, int]:
    pixmap = edit._preview.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    image = pixmap.toImage()
    pixel = image.pixelColor(image.width() // 2, image.height() // 2)
    return pixel.red(), pixel.green(), pixel.blue(), pixel.alpha()


class TestIconEdit:
    def test_value_defaults(self, qapp):
        assert_that(_edit().value()).is_equal_to({"ref": "", "color": "#ffffff"})

    def test_set_value_round_trips_and_emits_nothing(self, qapp):
        edit = _edit()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        edit.set_value({"ref": _REF, "color": "#11223380"})

        assert_that(edit.value()).is_equal_to({"ref": _REF, "color": "#11223380"})
        assert_that(emitted).is_empty()

    def test_garbage_value_uses_defaults(self, qapp):
        edit = _edit()
        edit.set_value("garbage")
        assert_that(edit.value()).is_equal_to({"ref": "", "color": "#ffffff"})
        edit.set_value({"ref": "pack:x", "color": "red"})
        assert_that(edit.value()).is_equal_to({"ref": "", "color": "#ffffff"})

    def test_browse_choice_sets_ref_and_emits(self, qapp, monkeypatch):
        import decker.client.widgets.icon_edit as module

        class FakeDialog(QObject):
            icon_chosen = pyqtSignal(str, str)

            def exec(self) -> None:
                self.icon_chosen.emit("com.x.p", "house.svg")

        monkeypatch.setattr(module, "IconBrowserDialog", lambda *a, **k: FakeDialog())
        edit = _edit()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        edit._browse()

        assert_that(edit.value()["ref"]).is_equal_to(_REF)
        assert_that(emitted).is_length(1)

    def test_browse_passes_the_fill_colour_to_the_dialog(self, qapp, monkeypatch):
        import decker.client.widgets.icon_edit as module

        seen: dict[str, Any] = {}

        class FakeDialog(QObject):
            icon_chosen = pyqtSignal(str, str)

            def __init__(self, _parent: Any, _rpc: Any, tint: str | None = None) -> None:
                super().__init__()
                seen["tint"] = tint

            def exec(self) -> None:
                pass

        monkeypatch.setattr(module, "IconBrowserDialog", FakeDialog)
        edit = _edit()
        edit.set_value({"color": "#ff0000"})

        edit._browse()

        assert_that(seen["tint"]).is_equal_to("#ff0000")

    def test_clear_resets_ref_keeps_colour_and_emits(self, qapp):
        edit = _edit()
        edit.set_value({"ref": _REF, "color": "#ff0000"})
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        edit._clear.click()

        assert_that(edit.value()).is_equal_to({"ref": "", "color": "#ff0000"})
        assert_that(emitted).is_length(1)

    def test_clear_is_disabled_without_an_icon(self, qapp):
        edit = _edit()
        assert_that(edit._clear.isEnabled()).is_false()
        edit.set_value({"ref": _REF})
        assert_that(edit._clear.isEnabled()).is_true()

    def test_colour_change_emits_and_updates_value(self, qapp):
        edit = _edit()
        emitted: list[None] = []
        edit.value_changed.connect(lambda: emitted.append(None))

        edit._colour.color_changed.emit("#00ff00")
        edit._colour.set_color("#00ff00")

        assert_that(edit.value()["color"]).is_equal_to("#00ff00")
        assert_that(emitted).is_length(1)

    def test_colour_swatch_shows_no_hex_name(self, qapp):
        edit = _edit()
        assert_that(edit._colour.text()).is_equal_to("")

    def test_name_label_shows_stem_or_no_icon(self, qapp):
        edit = _edit()
        assert_that(edit._name.text()).is_equal_to("No icon")
        edit.set_value({"ref": "pack:com.x.p/sub/house-alt.svg"})
        assert_that(edit._name.text()).is_equal_to("house-alt")

    def test_preview_uses_fill_colour(self, qapp):
        edit = _edit()

        edit.set_value({"ref": _REF, "color": "#ff0000"})

        assert_that(_centre(edit)).is_equal_to((255, 0, 0, 255))

    def test_colour_change_retints_the_preview_without_another_fetch(self, qapp):
        rpc = FakeRpc()
        edit = _edit(rpc)
        edit.set_value({"ref": _REF, "color": "#ff0000"})
        fetches = len(rpc.calls)

        edit._colour.set_color("#0000ff")
        edit._on_colour_changed("#0000ff")

        assert_that(_centre(edit)).is_equal_to((0, 0, 255, 255))
        assert_that(rpc.calls).is_length(fetches)

    def test_missing_icon_shows_placeholder_and_keeps_name(self, qapp):
        edit = _edit(FakeRpc(svg=None))

        edit.set_value({"ref": _REF})

        assert_that(edit._name.text()).is_equal_to("house")
        assert_that(edit._preview.pixmap().isNull()).is_false()
        assert_that(edit.value()["ref"]).is_equal_to(_REF)

    def test_no_connection_does_not_crash(self, qapp, monkeypatch):
        import decker.client.widgets.icon_edit as module

        class NoopDialog(QObject):
            icon_chosen = pyqtSignal(str, str)

            def __init__(self, *_a: Any, **_k: Any) -> None:
                super().__init__()

            def exec(self) -> None:
                pass

        monkeypatch.setattr(module, "IconBrowserDialog", NoopDialog)
        edit = IconEdit(lambda: None)

        edit.set_value({"ref": _REF})
        edit._browse()

        assert_that(edit._name.text()).is_equal_to("house")

    def test_default_rpc_resolves_the_app_context_lazily(self, qapp):
        from decker.client.context import AppContext

        rpc = FakeRpc()
        AppContext.get().connection_manager = rpc  # type: ignore[assignment]
        try:
            edit = IconEdit()
            edit.set_value({"ref": _REF})
            assert_that(rpc.calls).is_not_empty()
        finally:
            AppContext.get().connection_manager = None
