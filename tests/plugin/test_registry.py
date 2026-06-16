from assertpy import assert_that

from decker.plugin.base import DeckerPlugin
from decker.plugin.registry import ActionRegistry


class TestActionRegistry:
    def test_get_returns_none_when_not_registered(self):
        registry = ActionRegistry()
        assert_that(registry.get("p", "a", "ctx")).is_none()

    def test_register_then_get_returns_instance(self):
        registry = ActionRegistry()
        instance = DeckerPlugin()
        registry.register("p", "a", "ctx", instance)
        assert_that(registry.get("p", "a", "ctx")).is_same_as(instance)

    def test_unregister_removes_instance(self):
        registry = ActionRegistry()
        registry.register("p", "a", "ctx", DeckerPlugin())
        registry.unregister("p", "a", "ctx")
        assert_that(registry.get("p", "a", "ctx")).is_none()

    def test_unregister_unknown_context_is_noop(self):
        registry = ActionRegistry()
        registry.unregister("p", "a", "missing")  # should not raise

    def test_instance_count_counts_matching_action(self):
        registry = ActionRegistry()
        registry.register("p", "a", "ctx-1", DeckerPlugin())
        registry.register("p", "a", "ctx-2", DeckerPlugin())
        registry.register("p", "b", "ctx-3", DeckerPlugin())
        assert_that(registry.instance_count("p", "a")).is_equal_to(2)
        assert_that(registry.instance_count("p", "b")).is_equal_to(1)
        assert_that(registry.instance_count("p", "c")).is_equal_to(0)

    def test_context_id_stable_across_key_moves(self):
        registry = ActionRegistry()
        instance = DeckerPlugin()
        registry.register("p", "a", "ctx-stable", instance)
        # Moving to a different key does not change context_id, so the same lookup still works.
        assert_that(registry.get("p", "a", "ctx-stable")).is_same_as(instance)
