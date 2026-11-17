"""Tests for decker.client.update_runner."""

from unittest.mock import MagicMock

from assertpy import assert_that

from decker.client.update_runner import RESULT_OK, UpdateRunner


def test_runner_sequential():
    call = MagicMock(side_effect=["j1", "j2"])
    runner = UpdateRunner(call)

    runner.run(["a", "b"])

    assert_that(call.call_count).is_equal_to(1)
    call.assert_called_with("plugin_install_from_repository", "a")
    runner.on_finished("other", True, "")
    assert_that(call.call_count).is_equal_to(1)
    runner.on_finished("j1", True, "")
    assert_that(call.call_count).is_equal_to(2)
    call.assert_called_with("plugin_install_from_repository", "b")
    runner.on_finished("j2", False, "boom")
    assert_that(runner.results).is_equal_to({"a": RESULT_OK, "b": "boom"})
    assert_that(runner.busy).is_false()


def test_runner_records_busy_and_continues():
    call = MagicMock(side_effect=["error: another install is running", "j2"])
    done = MagicMock()
    runner = UpdateRunner(call, on_complete=done)

    runner.run(["a", "b"])
    runner.on_finished("j2", True, "")

    assert_that(runner.results).is_equal_to({"a": "another install is running", "b": RESULT_OK})
    done.assert_called_once_with(runner.results)


def test_runner_handles_finish_before_job_id_and_exceptions():
    runner = UpdateRunner(MagicMock())

    def call(_method, plugin_id):
        if plugin_id == "boom":
            raise OSError("down")
        runner.on_finished("j1", True, "")  # arrives before the call returns
        return "j1"

    runner._call = call  # pylint: disable=protected-access
    runner.run(["a", "boom"])

    assert_that(runner.results["a"]).is_equal_to(RESULT_OK)
    assert_that(runner.results["boom"]).contains("down")
    assert_that(runner.busy).is_false()


def test_runner_ignores_early_finish_for_another_job():
    runner = UpdateRunner(MagicMock())

    def call(_method, _plugin_id):
        runner.on_finished("someone-else", True, "")
        return "j1"

    runner._call = call  # pylint: disable=protected-access
    runner.run(["a"])

    assert_that(runner.busy).is_true()
    runner.on_finished("j1", False, "bad")
    assert_that(runner.results).is_equal_to({"a": "bad"})


def _deferred_runner():
    pending: list = []

    def submit(work, done):
        pending.append((work, done))

    runner = UpdateRunner(MagicMock(side_effect=["j1", "j2"]), submit=submit)
    return runner, pending


def _deliver(pending):
    work, done = pending.pop(0)
    try:
        result = work()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        result = exc
    done(result)


def test_start_call_is_submitted_not_run_inline():
    runner, pending = _deferred_runner()

    runner.run(["a"])

    assert_that(pending).is_length(1)
    assert_that(runner.busy).is_true()
    _deliver(pending)
    runner.on_finished("j1", True, "")
    assert_that(runner.results).is_equal_to({"a": RESULT_OK})


def test_finish_before_async_start_result_is_replayed():
    runner, pending = _deferred_runner()
    runner.run(["a"])

    runner.on_finished("j1", True, "")  # job finished before the start call's result was delivered
    _deliver(pending)

    assert_that(runner.results).is_equal_to({"a": RESULT_OK})
    assert_that(runner.busy).is_false()


def test_reset_reports_interrupted_item_and_ignores_late_start():
    done = MagicMock()
    pending: list = []
    runner = UpdateRunner(MagicMock(return_value="j1"), on_complete=done, submit=lambda w, d: pending.append((w, d)))
    runner.run(["a", "b"])

    runner.reset()

    assert_that(runner.busy).is_false()
    assert_that(runner.results["a"]).contains("Interrupted")
    assert_that(runner.results).does_not_contain_key("b")
    done.assert_called_once_with(runner.results)
    _deliver(pending)  # the stale start result must not revive the run
    assert_that(runner.busy).is_false()
    runner.run(["c"])
    assert_that(runner.busy).is_true()


def test_reset_when_idle_is_a_no_op():
    done = MagicMock()
    UpdateRunner(MagicMock(), on_complete=done).reset()
    done.assert_not_called()
