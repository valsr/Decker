from unittest.mock import MagicMock

from assertpy import assert_that

from decker.plugin.base import DeckerPlugin, action


class TestActionDecorator:
    def test_tags_class_with_action_uuid(self):
        @action("com.decker.clock.show")
        class ClockAction(DeckerPlugin):
            pass

        assert_that(ClockAction.action_uuid).is_equal_to("com.decker.clock.show")

    def test_default_handlers_are_no_ops(self):
        class NoopAction(DeckerPlugin):
            pass

        instance = NoopAction()
        ctx = MagicMock()
        instance.on_key_down(ctx)
        instance.on_key_up(ctx)
        instance.on_will_appear(ctx)
        instance.on_will_disappear(ctx)
        instance.on_settings_changed(ctx)
        ctx.assert_not_called()

    def test_overridden_handler_is_invoked(self):
        calls = []

        @action("com.decker.clock.show")
        class ClockAction(DeckerPlugin):
            def on_key_down(self, ctx):
                calls.append(ctx)

        instance = ClockAction()
        ctx = MagicMock()
        instance.on_key_down(ctx)
        assert_that(calls).is_equal_to([ctx])
