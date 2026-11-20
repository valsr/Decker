from assertpy import assert_that

from decker.client.icon_picker import NO_TINT
from decker.client.widgets.background_edit import BackgroundEdit
from decker.client.widgets.schema_form import AppearanceForm
from decker.common.appearance_schema import APPEARANCE_SCHEMA


def _bg(kind: str, color: str = "#000000", ref: str = "") -> dict:
    return {"type": kind, "color": color, "image": {"ref": ref}}


def _spy(edit: BackgroundEdit) -> list[int]:
    hits: list[int] = []
    edit.value_changed.connect(lambda: hits.append(1))
    return hits


class TestBackgroundEdit:  # pylint: disable=protected-access
    def test_modes_show_the_right_controls(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        for kind, colour, image in (("none", False, False), ("color", True, False), ("image", False, True)):
            edit.set_value(_bg(kind))
            assert_that(edit._colour.isHidden()).is_equal_to(not colour)
            assert_that(edit._image.isHidden()).is_equal_to(not image)

    def test_value_round_trip_for_each_mode(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        for value in (_bg("none", "#102030"), _bg("color", "#11223380"), _bg("image", "#000000", "pack:p/a.png")):
            edit.set_value(value)
            assert_that(edit.value()).is_equal_to(value)

    def test_legacy_string_value_shows_as_color_mode(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        edit.set_value("#336699")
        assert_that(edit.value()).is_equal_to(_bg("color", "#336699"))

    def test_switching_modes_keeps_the_other_modes_choice(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        edit.set_value(_bg("image", "#336699", "pack:p/a.png"))
        edit._mode.setCurrentIndex(edit._mode.findData("color"))
        assert_that(edit.value()["image"]).is_equal_to({"ref": "pack:p/a.png"})
        edit._mode.setCurrentIndex(edit._mode.findData("image"))
        assert_that(edit.value()).is_equal_to(_bg("image", "#336699", "pack:p/a.png"))

    def test_changes_emit_value_changed_once(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        hits = _spy(edit)
        edit._mode.setCurrentIndex(edit._mode.findData("image"))
        assert_that(hits).is_length(1)
        edit._image.clear_icon()
        assert_that(hits).is_length(2)
        edit._colour.color_changed.emit("#ffffff")
        assert_that(hits).is_length(3)

    def test_set_value_does_not_emit(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        hits = _spy(edit)
        edit.set_value(_bg("image", "#336699", "pack:p/a.png"))
        edit.set_value("#abcdef")
        assert_that(hits).is_empty()

    def test_empty_image_ref_keeps_type_image(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        edit.set_value(_bg("image"))
        assert_that(edit.value()["type"]).is_equal_to("image")
        assert_that(edit.value()["image"]).is_equal_to({"ref": ""})

    def test_schema_form_builds_background_field_and_reports_edits(self, qapp):  # pylint: disable=unused-argument
        form = AppearanceForm()
        hits: list[int] = []
        form.changed.connect(lambda: hits.append(1))
        form.set_schema(APPEARANCE_SCHEMA, {"background": "#336699"})
        field = form._fields["background"]

        assert isinstance(field.widget, BackgroundEdit)
        assert_that(form.values()["background"]).is_equal_to(_bg("color", "#336699"))
        field.widget._mode.setCurrentIndex(field.widget._mode.findData("none"))
        assert_that(hits).is_length(1)
        assert_that(form.values()["background"]["type"]).is_equal_to("none")


class TestBackgroundEditImagePrompt:  # pylint: disable=protected-access
    def test_empty_image_shows_placeholder_and_a_clickable_thumbnail(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        edit.set_value(_bg("image"))
        image = edit._image
        assert_that(image._name.text()).is_equal_to("No image (shows black)")
        assert_that(image._preview.toolTip()).is_equal_to("Click to choose an image")
        opened: list[bool] = []
        monkeypatch.setattr(image, "browse", lambda: opened.append(True))
        image._preview.clicked.emit()
        assert_that(opened).is_equal_to([True])
        assert_that(image._clear.toolTip()).is_equal_to("Remove the background image")

    def test_placeholder_updates_after_choosing_and_clearing(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        edit.set_value(_bg("image"))
        hits = _spy(edit)
        edit._image._on_icon_chosen("p", "a.png")
        assert_that(hits).is_length(1)
        assert_that(edit.value()["image"]["ref"]).is_equal_to("pack:p/a.png")
        assert_that(edit._image._name.text()).is_not_equal_to("No image (shows black)")
        edit._image.clear_icon()
        assert_that(edit._image._name.text()).is_equal_to("No image (shows black)")

    def test_modes_keep_choices_in_both_directions(self, qapp):  # pylint: disable=unused-argument
        edit = BackgroundEdit()
        edit.set_value(_bg("color", "#336699", "pack:p/a.png"))
        for first, second in (("image", "color"), ("none", "color")):
            edit._mode.setCurrentIndex(edit._mode.findData(first))
            edit._mode.setCurrentIndex(edit._mode.findData(second))
            assert_that(edit.value()).is_equal_to(_bg("color", "#336699", "pack:p/a.png"))
        edit.set_value(_bg("image", "#336699", "pack:p/a.png"))
        edit._mode.setCurrentIndex(edit._mode.findData("color"))
        edit._mode.setCurrentIndex(edit._mode.findData("image"))
        assert_that(edit.value()).is_equal_to(_bg("image", "#336699", "pack:p/a.png"))


def test_background_image_thumbnail_and_browser_are_untinted(qapp, monkeypatch):  # pylint: disable=unused-argument
    seen: list[tuple] = []

    class FakeDialog:
        icon_chosen = type("S", (), {"connect": lambda *_a: None})()

        def __init__(self, *args) -> None:
            seen.append(args)

        def exec(self) -> None:
            pass

    monkeypatch.setattr("decker.client.widgets.icon_edit.IconBrowserDialog", FakeDialog)
    edit = BackgroundEdit()
    edit.set_value(_bg("image"))

    edit._image.browse()  # pylint: disable=protected-access

    assert_that(edit._image._thumb_tint()).is_none()  # pylint: disable=protected-access
    assert_that(seen).is_length(1)
    assert_that(seen[0][2]).is_equal_to(NO_TINT)
