"""Tests for decker.client.views.base.BaseView."""

from assertpy import assert_that

from decker.client.events import KeyEvent
from decker.client.views.base import BaseView


class _ConcreteView(BaseView):
    def __init__(self):
        super().__init__()
        self.activated = False
        self.deactivated = False

    def on_activate(self) -> None:
        self.activated = True

    def on_deactivate(self) -> None:
        self.deactivated = True


class TestBaseView:
    def test_handle_event_is_a_noop_by_default(self, qapp):  # pylint: disable=unused-argument
        view = _ConcreteView()

        view.handle_event(KeyEvent(device_id="abc123", key_index=0, pressed=True))  # should not raise

        assert_that(view.activated).is_false()
        assert_that(view.deactivated).is_false()

    def test_subclass_lifecycle_hooks_are_invoked(self, qapp):  # pylint: disable=unused-argument
        view = _ConcreteView()

        view.on_activate()
        view.on_deactivate()

        assert_that(view.activated).is_true()
        assert_that(view.deactivated).is_true()
