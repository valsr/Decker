import time

from assertpy import assert_that

from decker.plugin.executor import PluginExecutor


class TestPluginExecutor:
    def test_dispatch_runs_callback(self):
        executor = PluginExecutor()
        calls: list[str] = []
        executor.dispatch("p", calls.append, "called")
        executor.shutdown()
        assert_that(calls).is_equal_to(["called"])

    def test_dispatch_swallows_exception(self):
        executor = PluginExecutor()

        def raises():
            raise ValueError("boom")

        executor.dispatch("p", raises)  # must not propagate
        executor.shutdown()

    def test_dispatch_times_out_without_crashing(self):
        executor = PluginExecutor(timeout=0.1)
        executor.dispatch("p", time.sleep, 1)  # logs a timeout, does not raise
        executor.shutdown()

    def test_one_failing_callback_does_not_block_another(self):
        executor = PluginExecutor()
        calls: list[str] = []

        def raises():
            raise RuntimeError("boom")

        executor.dispatch("p", raises)
        executor.dispatch("p", calls.append, "still works")
        executor.shutdown()
        assert_that(calls).is_equal_to(["still works"])
