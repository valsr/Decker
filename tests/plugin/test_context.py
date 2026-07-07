from unittest.mock import MagicMock

from assertpy import assert_that

from decker.plugin.context import ActionContext, ActionTarget

_TARGET = ActionTarget(
    plugin_uuid="com.decker.clock",
    action_uuid="com.decker.clock.show",
    context_id="ctx-1",
    device_id="abc12345",
    key_index=3,
)


def _make_context(sink=None, settings_store=None):
    return ActionContext(_TARGET, sink or MagicMock(), settings_store or MagicMock())


class TestHardwareDelegation:
    def test_set_image_delegates_to_sink(self):
        sink = MagicMock()
        ctx = _make_context(sink=sink)
        ctx.set_image(b"image-bytes")
        sink.set_image.assert_called_once_with("abc12345", 3, b"image-bytes")

    def test_set_title_delegates_to_sink(self):
        sink = MagicMock()
        ctx = _make_context(sink=sink)
        ctx.set_title("Hello")
        sink.set_title.assert_called_once_with("abc12345", 3, "Hello")

    def test_set_state_delegates_to_sink(self):
        sink = MagicMock()
        ctx = _make_context(sink=sink)
        ctx.set_state(1)
        sink.set_state.assert_called_once_with("abc12345", 3, 1)

    def test_show_alert_delegates_to_sink(self):
        sink = MagicMock()
        ctx = _make_context(sink=sink)
        ctx.show_alert()
        sink.show_alert.assert_called_once_with("abc12345", 3)

    def test_show_ok_delegates_to_sink(self):
        sink = MagicMock()
        ctx = _make_context(sink=sink)
        ctx.show_ok()
        sink.show_ok.assert_called_once_with("abc12345", 3)


class TestSettings:
    def test_set_settings_delegates_to_store(self):
        store = MagicMock()
        ctx = _make_context(settings_store=store)
        ctx.set_settings({"foo": "bar"})
        store.set_settings.assert_called_once_with("com.decker.clock", "com.decker.clock.show", "ctx-1", {"foo": "bar"})

    def test_get_settings_delegates_to_store(self):
        store = MagicMock()
        store.get_settings.return_value = {"foo": "bar"}
        ctx = _make_context(settings_store=store)
        assert_that(ctx.get_settings()).is_equal_to({"foo": "bar"})
        store.get_settings.assert_called_once_with("com.decker.clock", "com.decker.clock.show", "ctx-1")
