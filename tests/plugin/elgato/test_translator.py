import base64
from unittest.mock import MagicMock

from assertpy import assert_that

from decker.plugin.context import ActionTarget
from decker.plugin.elgato.protocol import ElgatoEvent
from decker.plugin.elgato.translator import ElgatoEventTranslator

_TARGET = ActionTarget(plugin_uuid="p", action_uuid="a", context_id="ctx-1", device_id="dev-1", key_index=2)


def _make_translator():
    sink = MagicMock()
    settings_store = MagicMock()
    return ElgatoEventTranslator(sink, settings_store), sink, settings_store


class TestElgatoEventTranslator:
    def test_set_title_calls_sink(self):
        translator, sink, _ = _make_translator()
        event = ElgatoEvent(event="setTitle", payload={"title": "Hello"})
        translator.apply(event, _TARGET)
        sink.set_title.assert_called_once_with("dev-1", 2, "Hello")

    def test_set_image_decodes_base64_payload(self):
        translator, sink, _ = _make_translator()
        encoded = base64.b64encode(b"raw-bytes").decode()
        event = ElgatoEvent(event="setImage", payload={"image": encoded})
        translator.apply(event, _TARGET)
        sink.set_image.assert_called_once_with("dev-1", 2, b"raw-bytes")

    def test_set_image_empty_payload_sends_empty_bytes(self):
        translator, sink, _ = _make_translator()
        event = ElgatoEvent(event="setImage", payload={})
        translator.apply(event, _TARGET)
        sink.set_image.assert_called_once_with("dev-1", 2, b"")

    def test_set_state_calls_sink(self):
        translator, sink, _ = _make_translator()
        event = ElgatoEvent(event="setState", payload={"state": 1})
        translator.apply(event, _TARGET)
        sink.set_state.assert_called_once_with("dev-1", 2, 1)

    def test_show_alert_calls_sink(self):
        translator, sink, _ = _make_translator()
        translator.apply(ElgatoEvent(event="showAlert"), _TARGET)
        sink.show_alert.assert_called_once_with("dev-1", 2)

    def test_show_ok_calls_sink(self):
        translator, sink, _ = _make_translator()
        translator.apply(ElgatoEvent(event="showOk"), _TARGET)
        sink.show_ok.assert_called_once_with("dev-1", 2)

    def test_set_settings_calls_store(self):
        translator, _, settings_store = _make_translator()
        event = ElgatoEvent(event="setSettings", context="ctx-1", payload={"foo": "bar"})
        translator.apply(event, _TARGET)
        settings_store.set_settings.assert_called_once_with("p", "a", "ctx-1", {"foo": "bar"})

    def test_unknown_event_is_ignored(self):
        translator, sink, settings_store = _make_translator()
        translator.apply(ElgatoEvent(event="somethingElse"), _TARGET)
        assert_that(sink.mock_calls).is_empty()
        assert_that(settings_store.mock_calls).is_empty()
