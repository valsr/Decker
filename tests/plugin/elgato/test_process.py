from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.plugin.elgato.process import (
    ElgatoPluginProcess,
    ElgatoPluginProcessError,
    ElgatoProcessConfig,
)


def _make_config(tmp_path, node_path="node"):
    return ElgatoProcessConfig(
        plugin_dir=tmp_path, entry_point="app.js", port=28196, plugin_uuid="com.elgato.test", node_path=node_path
    )


class TestElgatoPluginProcess:
    def test_start_raises_clear_error_when_node_missing(self, tmp_path):
        process = ElgatoPluginProcess(_make_config(tmp_path, node_path="not-a-real-binary"))
        with pytest.raises(ElgatoPluginProcessError, match="Node.js executable"):
            process.start()

    def test_is_running_false_before_start(self, tmp_path):
        process = ElgatoPluginProcess(_make_config(tmp_path))
        assert_that(process.is_running).is_false()

    def test_start_spawns_subprocess_with_expected_args(self, tmp_path):
        with patch("decker.plugin.elgato.process.subprocess.Popen") as mock_popen:
            mock_popen.return_value.poll.return_value = None
            process = ElgatoPluginProcess(_make_config(tmp_path))
            process.start()
            mock_popen.assert_called_once_with(
                ["node", "app.js", "-port", "28196", "-pluginUUID", "com.elgato.test"], cwd=tmp_path
            )
            assert_that(process.is_running).is_true()

    def test_start_is_noop_if_already_running(self, tmp_path):
        with patch("decker.plugin.elgato.process.subprocess.Popen") as mock_popen:
            mock_popen.return_value.poll.return_value = None
            process = ElgatoPluginProcess(_make_config(tmp_path))
            process.start()
            process.start()
            mock_popen.assert_called_once()

    def test_stop_terminates_running_process(self, tmp_path):
        with patch("decker.plugin.elgato.process.subprocess.Popen") as mock_popen:
            proc = MagicMock()
            proc.poll.return_value = None
            mock_popen.return_value = proc
            process = ElgatoPluginProcess(_make_config(tmp_path))
            process.start()
            process.stop()
            proc.terminate.assert_called_once()
            assert_that(process.is_running).is_false()

    def test_stop_without_start_is_noop(self, tmp_path):
        process = ElgatoPluginProcess(_make_config(tmp_path))
        process.stop()  # should not raise
