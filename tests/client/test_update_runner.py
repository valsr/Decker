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
