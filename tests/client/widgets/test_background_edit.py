from assertpy import assert_that

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
