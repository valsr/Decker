from typing import Any

from assertpy import assert_that
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from decker.client.widgets.color_button import ColorButton
from decker.client.widgets.schema_form import AppearanceForm, SchemaForm
from decker.client.widgets.text_style_edit import TextStyleEdit
from decker.common.model import DeviceHardwareInfo
from decker.common.text_style import TEXT_STYLE_DEFAULTS


def _form(schema: list[dict[str, Any]], values: dict[str, Any] | None = None) -> SchemaForm:
    form = SchemaForm()
    form.set_schema(schema, values or {})
    return form


class TestSchemaForm:  # pylint: disable=protected-access
    def test_int_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "n", "type": "int", "label": "N", "default": 1, "min": 1, "max": 9}], {"n": 5})
        assert_that(form.values()).is_equal_to({"n": 5})

    def test_int_special_value_text(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "n", "type": "int", "default": 0, "min": 0, "special_value": "No limit"}])
        spin = form._fields["n"].widget
        assert isinstance(spin, QSpinBox)
        assert_that(spin.specialValueText()).is_equal_to("No limit")

    def test_optional_int_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "n", "type": "int", "optional": True}], {"n": 4})
        assert_that(form.values()).is_equal_to({"n": 4})

    def test_optional_int_empty_is_none(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "n", "type": "int", "optional": True}], {"n": 4})
        widget = form._fields["n"].widget
        assert isinstance(widget, QLineEdit)
        widget.setText("")
        assert_that(form.values()["n"]).is_none()

    def test_float_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "f", "type": "float", "default": 1.0, "min": 0, "max": 5, "step": 0.5, "decimals": 2}])
        form._fields["f"].set(2.25)
        assert_that(form.values()["f"]).is_equal_to(2.25)

    def test_text_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "t", "type": "text", "default": "", "placeholder": "hint"}], {"t": "hello"})
        assert_that(form.values()).is_equal_to({"t": "hello"})
        widget = form._fields["t"].widget
        assert isinstance(widget, QLineEdit)
        assert_that(widget.placeholderText()).is_equal_to("hint")

    def test_multiline_text_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "t", "type": "text", "multiline": True, "placeholder": "p"}], {"t": "a\nb"})
        assert isinstance(form._fields["t"].widget, QPlainTextEdit)
        assert_that(form.values()["t"]).is_equal_to("a\nb")

    def test_bool_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "b", "type": "bool", "default": False}], {"b": True})
        assert isinstance(form._fields["b"].widget, QCheckBox)
        assert_that(form.values()["b"]).is_true()

    def test_choice_round_trips(self, qapp):  # pylint: disable=unused-argument
        schema = [
            {
                "key": "c",
                "type": "choice",
                "default": "a",
                "options": [{"label": "A", "value": "a"}, {"label": "B", "value": "b"}],
            }
        ]
        assert_that(_form(schema, {"c": "b"}).values()["c"]).is_equal_to("b")
        assert_that(_form(schema, {"c": "zzz"}).values()["c"]).is_equal_to("a")

    def test_color_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "c", "type": "color", "default": "#000000"}], {"c": "#123456"})
        assert_that(form.values()["c"]).is_equal_to("#123456")

    def test_optional_color_round_trips_and_unchecked_is_none(self, qapp):  # pylint: disable=unused-argument
        schema = [{"key": "c", "type": "color", "optional": True}]
        assert_that(_form(schema, {"c": "#123456"}).values()["c"]).is_equal_to("#123456")
        assert_that(_form(schema, {}).values()["c"]).is_none()

    def test_font_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "f", "type": "font", "default": "DejaVu Sans"}], {"f": "DejaVu Sans"})
        assert_that(form.values()["f"]).is_instance_of(str).is_not_empty()

    def test_icon_round_trips(self, qapp):  # pylint: disable=unused-argument
        value = {"ref": "pack:p/a.svg", "color": "#112233"}
        form = _form([{"key": "i", "type": "icon"}], {"i": value})
        assert_that(form.values()["i"]).is_equal_to(value)

    def test_sections_render_as_headings(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"section": "Counting"}, {"key": "n", "type": "bool"}])
        titles = [lb.text() for lb in form.findChildren(QLabel) if lb.property("role") == "title"]
        assert_that(titles).is_equal_to(["Counting"])

    def test_help_becomes_tooltip(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "n", "type": "bool", "help": "Explains"}])
        assert_that(form._fields["n"].widget.toolTip()).is_equal_to("Explains")

    def test_values_returns_defaults_for_untouched_fields(self, qapp):  # pylint: disable=unused-argument
        schema: list[dict[str, Any]] = [
            {"key": "n", "type": "int", "default": 3, "min": 0, "max": 9},
            {"key": "t", "type": "text", "default": "x"},
            {"key": "b", "type": "bool", "default": True},
        ]
        assert_that(_form(schema).values()).is_equal_to({"n": 3, "t": "x", "b": True})

    def test_set_schema_replaces_previous_fields(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "a", "type": "bool"}])
        form.set_schema([{"key": "b", "type": "bool"}], {})
        assert_that(form.values()).contains_key("b").does_not_contain_key("a")


class TestTextStyleField:  # pylint: disable=protected-access
    _ENTRY: dict[str, Any] = {"key": "label", "type": "text_style", "label": "Label"}

    def test_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([self._ENTRY], {"label": {"text": "Hi", "bold": True}})
        assert isinstance(form._fields["label"].widget, TextStyleEdit)
        assert_that(form.values()["label"]).is_equal_to({**TEXT_STYLE_DEFAULTS, "text": "Hi", "bold": True})

    def test_default_applied(self, qapp):  # pylint: disable=unused-argument
        default = {**TEXT_STYLE_DEFAULTS, "position": "top"}
        form = _form([{**self._ENTRY, "default": default}])
        assert_that(form.values()["label"]).is_equal_to(default)

    def test_two_fields_are_independent(self, qapp):  # pylint: disable=unused-argument
        form = _form([self._ENTRY, {**self._ENTRY, "key": "other", "label": "Other"}], {"label": {"text": "A"}})
        form._fields["other"].set({"text": "B", "italic": True})
        assert_that(form.values()["label"]["text"]).is_equal_to("A")
        assert_that(form.values()["label"]["italic"]).is_false()
        assert_that(form.values()["other"]).contains_entry({"text": "B"}, {"italic": True})

    def test_row_label(self, qapp):  # pylint: disable=unused-argument
        form = _form([self._ENTRY])
        assert_that([lb.text() for lb in form.findChildren(QLabel)]).contains("Label:")


class TestAlphaColorField:  # pylint: disable=protected-access
    _ENTRY: dict[str, Any] = {"key": "bg", "type": "color", "default": "#000000", "alpha": True}

    def test_rgba_round_trips(self, qapp):  # pylint: disable=unused-argument
        form = _form([self._ENTRY], {"bg": "#11223380"})
        assert_that(form.values()["bg"]).is_equal_to("#11223380")

    def test_plain_color_field_ignores_rgba(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "bg", "type": "color", "default": "#000000"}], {"bg": "#11223380"})
        assert_that(form.values()["bg"]).is_equal_to("#000000")


class TestAppearanceForm:  # pylint: disable=protected-access
    _SCHEMA: list[dict[str, Any]] = [
        {"section": "Ignored"},
        {"key": "title", "type": "text_style", "label": "Title"},
        {"key": "icon", "type": "icon", "label": "Icon"},
        {"key": "background", "type": "color", "label": "Background", "default": "#000000", "alpha": True},
    ]

    def test_text_style_has_its_own_row_and_the_rest_share_one(self, qapp):  # pylint: disable=unused-argument
        form = AppearanceForm()
        form.set_schema(self._SCHEMA, {})

        layout = form.layout()
        assert isinstance(layout, QVBoxLayout)
        assert_that(layout.count()).is_equal_to(2)
        texts = [lb.text() for lb in form.findChildren(QLabel) if lb.text().endswith(":")]
        assert_that(texts).is_equal_to(["Title:", "Icon:", "Background:"])
        first, second = (layout.itemAt(i).layout() for i in range(2))  # type: ignore[union-attr]
        assert first is not None and second is not None
        assert_that(first.indexOf(form._fields["title"].widget)).is_greater_than_or_equal_to(0)
        assert_that(second.indexOf(form._fields["icon"].widget)).is_less_than(
            second.indexOf(form._fields["background"].widget)
        )

    def test_colour_fields_are_swatch_only(self, qapp):  # pylint: disable=unused-argument
        form = AppearanceForm()
        form.set_schema(self._SCHEMA, {"background": "#11223380"})

        button = form._fields["background"].widget
        assert isinstance(button, ColorButton)
        assert_that(button.text()).is_equal_to("")
        assert_that(button.toolTip()).is_equal_to("#11223380")

    def test_regular_form_still_shows_the_colour_name(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "bg", "type": "color", "default": "#000000"}], {"bg": "#112233"})
        button = form._fields["bg"].widget
        assert isinstance(button, ColorButton)
        assert_that(button.text()).is_equal_to("#112233")

    def test_values_round_trip(self, qapp):  # pylint: disable=unused-argument
        form = AppearanceForm()
        form.set_schema(self._SCHEMA, {"title": {"text": "Hi"}, "background": "#11223380"})

        values = form.values()

        assert_that(values["title"]["text"]).is_equal_to("Hi")
        assert_that(values["background"]).is_equal_to("#11223380")

    def test_set_schema_twice_replaces_fields(self, qapp):  # pylint: disable=unused-argument
        form = AppearanceForm()
        form.set_schema(self._SCHEMA, {})
        form.set_schema(self._SCHEMA[1:2], {})

        assert_that(list(form.values())).is_equal_to(["title"])
        assert_that([lb.text() for lb in form.findChildren(QLabel)]).is_equal_to(["Title:"])

    def test_edits_emit_changed_but_loading_does_not(self, qapp):  # pylint: disable=unused-argument
        form = AppearanceForm()
        seen: list[bool] = []
        form.changed.connect(lambda: seen.append(True))
        form.set_schema(self._SCHEMA, {"title": {"text": "Hi"}})
        assert_that(seen).is_empty()

        form._fields["background"].set("#445566")
        form._fields["background"].widget.color_changed.emit("#445566")  # type: ignore[attr-defined]
        form._fields["icon"].widget.value_changed.emit()  # type: ignore[attr-defined]

        assert_that(seen).is_length(2)


class TestIconField:  # pylint: disable=protected-access
    def test_builds_an_icon_edit(self, qapp):  # pylint: disable=unused-argument
        from decker.client.widgets.icon_edit import (
            IconEdit,  # pylint: disable=import-outside-toplevel
        )

        form = _form([{"key": "i", "type": "icon", "label": "Icon"}])
        assert isinstance(form._fields["i"].widget, IconEdit)
        assert_that([lb.text() for lb in form.findChildren(QLabel)]).contains("Icon:")

    def test_default_applied(self, qapp):  # pylint: disable=unused-argument
        default = {"ref": "pack:p/a.svg", "color": "#ff0000"}
        form = _form([{"key": "i", "type": "icon", "default": default}])
        assert_that(form.values()["i"]).is_equal_to(default)

    def test_garbage_value_uses_defaults(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "i", "type": "icon"}], {"i": "/tmp/a.png"})
        assert_that(form.values()["i"]).is_equal_to({"ref": "", "color": "#ffffff"})


class TestPageField:
    def test_schema_form_builds_a_page_edit_and_round_trips(self, qapp):  # pylint: disable=unused-argument
        from decker.client.widgets.page_edit import PageEdit

        form = _form([{"key": "p", "type": "page", "label": "Page"}], {"p": "abc"})

        assert_that(form.findChild(PageEdit)).is_not_none()
        assert_that(form.values()["p"]).is_equal_to("abc")


class TestSchemaFormChanged:  # pylint: disable=protected-access
    def test_every_control_kind_emits_changed(self, qapp):  # pylint: disable=unused-argument
        schema: list[dict[str, Any]] = [
            {"key": "n", "type": "int", "default": 1},
            {"key": "t", "type": "text"},
            {"key": "b", "type": "bool"},
            {"key": "c", "type": "choice", "options": [{"label": "A", "value": "a"}, {"label": "B", "value": "b"}]},
            {"key": "col", "type": "color"},
        ]
        form = _form(schema)
        seen: list[bool] = []
        form.changed.connect(lambda: seen.append(True))

        form._fields["n"].widget.setValue(5)  # type: ignore[attr-defined]
        form._fields["t"].widget.setText("x")  # type: ignore[attr-defined]
        form._fields["b"].widget.setChecked(True)  # type: ignore[attr-defined]
        form._fields["c"].widget.setCurrentIndex(1)  # type: ignore[attr-defined]
        form._fields["col"].widget.color_changed.emit("#ffffff")  # type: ignore[attr-defined]

        assert_that(len(seen)).is_greater_than_or_equal_to(5)

    def test_loading_values_does_not_emit_changed(self, qapp):  # pylint: disable=unused-argument
        form = SchemaForm()
        seen: list[bool] = []
        form.changed.connect(lambda: seen.append(True))

        form.set_schema([{"key": "n", "type": "int"}, {"key": "t", "type": "text"}], {"n": 3, "t": "x"})

        assert_that(seen).is_empty()


class TestChangedEmitsOncePerEdit:  # pylint: disable=protected-access
    def _count(self, form, edit) -> int:
        seen: list[bool] = []
        form.changed.connect(lambda: seen.append(True))
        edit()
        return len(seen)

    def test_a_spinbox_change_emits_once(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "n", "type": "int", "default": 1}])
        spin = form._fields["n"].widget

        assert_that(self._count(form, lambda: spin.setValue(4))).is_equal_to(1)  # type: ignore[attr-defined]

    def test_a_font_change_emits_once(self, qapp):  # pylint: disable=unused-argument
        form = _form([{"key": "f", "type": "font"}])
        combo = form._fields["f"].widget

        assert_that(self._count(form, lambda: combo.setCurrentIndex(1))).is_equal_to(1)  # type: ignore[attr-defined]

    def test_a_title_style_change_emits_once(self, qapp):  # pylint: disable=unused-argument
        form = AppearanceForm()
        form.set_schema([{"key": "title", "type": "text_style", "label": "Title"}], {})
        edit = form._fields["title"].widget

        count = self._count(form, lambda: edit._toolbar._size.setValue(30))  # type: ignore[attr-defined]

        assert_that(count).is_equal_to(1)

    def test_an_icon_colour_change_emits_once(self, qapp, tmp_path):  # pylint: disable=unused-argument
        form = AppearanceForm()
        form.set_schema([{"key": "icon", "type": "icon", "label": "Icon"}], {})
        edit = form._fields["icon"].widget

        count = self._count(form, lambda: edit._on_colour_changed("#123456"))  # type: ignore[attr-defined]

        assert_that(count).is_equal_to(1)


class TestCompactIcon:  # pylint: disable=protected-access
    def test_the_appearance_form_uses_a_compact_icon_row_and_regular_forms_do_not(
        self, qapp
    ):  # pylint: disable=unused-argument
        appearance = AppearanceForm()
        appearance.set_schema([{"key": "icon", "type": "icon", "label": "Icon"}], {})
        regular = _form([{"key": "icon", "type": "icon", "label": "Icon"}])

        assert_that(appearance._fields["icon"].widget._compact).is_true()  # type: ignore[attr-defined]
        assert_that(regular._fields["icon"].widget._compact).is_false()  # type: ignore[attr-defined]


class TestProfileFields:  # pylint: disable=protected-access
    def setup_method(self):
        from decker.client.context import AppContext

        AppContext._instance = None
        self.calls: list[tuple[Any, ...]] = []
        outer = self

        class _Rpc:
            def call(self, method, *args):
                import json

                outer.calls.append((method, *args))
                if method == "profiles_list":
                    profiles = [{"profile_id": 0, "name": "Default"}, {"profile_id": 2, "name": "Work"}]
                    return json.dumps({"device_id": "dev1", "profiles": profiles, "active_profile_id": 0})
                pages = [("w1", "Docs")] if args[1:] == (2,) else [("p1", "Home"), ("p2", "More")]
                return json.dumps({"pages": [{"page_id": i, "name": n} for i, n in pages]})

        context = AppContext.get()
        context.connection_manager = _Rpc()  # type: ignore[assignment]
        context.active_device = DeviceHardwareInfo(id="dev1", type="Deck", vendor_id=0, product_id=0, num_keys=6)

    _SCHEMA = [
        {"key": "who", "type": "profile", "label": "Profile"},
        {"key": "where", "type": "page", "label": "Page", "profile_field": "who"},
    ]

    def test_builds_a_profile_edit_and_round_trips(self, qapp):  # pylint: disable=unused-argument
        from decker.client.widgets.profile_edit import ProfileEdit

        form = _form(self._SCHEMA, {"who": "2", "where": "w1"})

        assert_that(form.findChild(ProfileEdit)).is_not_none()
        assert_that(form.values()).is_equal_to({"who": "2", "where": "w1"})

    def test_the_page_list_follows_the_stored_profile_on_load(self, qapp):  # pylint: disable=unused-argument
        from decker.client.widgets.page_edit import PageEdit

        form = _form(self._SCHEMA, {"who": "2", "where": "w1"})
        page = form.findChild(PageEdit)

        assert_that([page.itemText(i) for i in range(page.count())]).is_equal_to(["(no page)", "Docs"])
        assert_that(page.value()).is_equal_to("w1")

    def test_changing_the_profile_reloads_and_clears_the_page_and_emits_changed(
        self, qapp
    ):  # pylint: disable=unused-argument
        from decker.client.widgets.page_edit import PageEdit
        from decker.client.widgets.profile_edit import ProfileEdit

        form = _form(self._SCHEMA, {"who": "", "where": "p2"})
        seen: list[bool] = []
        form.changed.connect(lambda: seen.append(True))
        profile, page = form.findChild(ProfileEdit), form.findChild(PageEdit)

        profile.setCurrentIndex(2)
        profile.activated.emit(2)

        assert_that(profile.value()).is_equal_to("2")
        assert_that(page.value()).is_equal_to("")
        assert_that([page.itemText(i) for i in range(page.count())]).is_equal_to(["(no page)", "Docs"])
        assert_that(seen).is_not_empty()

    def test_profile_field_may_come_after_the_page_field(self, qapp):  # pylint: disable=unused-argument
        from decker.client.widgets.page_edit import PageEdit

        form = _form(list(reversed(self._SCHEMA)), {"who": "2", "where": "w1"})

        assert_that(form.findChild(PageEdit).value()).is_equal_to("w1")
