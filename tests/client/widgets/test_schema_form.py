from typing import Any

from assertpy import assert_that
from PyQt6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPlainTextEdit, QSpinBox

from decker.client.widgets.schema_form import SchemaForm
from decker.client.widgets.text_style_edit import TextStyleEdit
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
        form = _form([{"key": "i", "type": "icon"}], {"i": "/tmp/a.png"})
        assert_that(form.values()["i"]).is_equal_to("/tmp/a.png")

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
