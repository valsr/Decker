"""Tests for decker.client.context."""

from assertpy import assert_that

from decker.client.context import AppContext


class TestAppContext:
    def setup_method(self):
        AppContext._instance = None  # pylint: disable=protected-access

    def test_get_returns_same_instance(self):
        assert_that(AppContext.get()).is_same_as(AppContext.get())

    def test_get_creates_instance_with_defaults(self):
        ctx = AppContext.get()
        assert_that(ctx.connected).is_false()
        assert_that(ctx.active_device).is_none()
        assert_that(ctx.last_command).is_none()
        assert_that(ctx.window).is_none()

    def test_reset_replaces_instance_with_fresh_state(self):
        ctx = AppContext.get()
        ctx.connected = True
        ctx.active_device = "abc123"

        AppContext.reset()
        new_ctx = AppContext.get()

        assert_that(new_ctx).is_not_same_as(ctx)
        assert_that(new_ctx.connected).is_false()
        assert_that(new_ctx.active_device).is_none()
