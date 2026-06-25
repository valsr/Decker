"""Tests for the server monitor — focuses on the internal state-machine logic."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.common.context import ServerAppContext
from decker.server.monitor import ServerMonitor, _read_rss_bytes
from decker.server.service import DeckerServiceStatus, DeckerStatusEnum


class TestReadRssBytes:
    def test_reads_vmrss_from_proc_status(self):
        content = "Name:\tpython\nVmRSS:\t  4096 kB\nVmPeak:\t 8192 kB\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            fh.write(content)
            path = fh.name
        try:
            pid = int(path)  # won't work as int — use a pid override approach
        except ValueError:
            pass
        # Patch builtins.open to feed our fake /proc content
        with (
            patch("builtins.open", return_value=open(path))
            if False
            else patch(
                "decker.server.monitor.open",
                side_effect=lambda p, **kw: open(path),
            )
        ):
            result = _read_rss_bytes(12345)
        os.unlink(path)
        assert_that(result).is_equal_to(4096 * 1024)

    def test_returns_none_when_file_missing(self):
        result = _read_rss_bytes(9999999)
        assert_that(result).is_none()

    def test_returns_none_on_value_error(self):
        with patch("builtins.open", side_effect=ValueError("bad value")):
            result = _read_rss_bytes(1)
        assert_that(result).is_none()


def _make_monitor() -> ServerMonitor:
    with patch("decker.server.monitor.config") as mock_cfg:
        mock_cfg.get_as.side_effect = lambda key, typ: {
            "server.port": 18861,
            "server.startup_wait": 5.0,
            "server.health_check_interval": 5.0,
            "server.max_failed_heartbeats": 3,
            "server.memory_limit": 1024 * 1024 * 1024,
        }[key]
        with patch("decker.server.monitor.ServerProcess") as MockServerProcess:
            m = ServerMonitor(ServerAppContext())
            m._server = MockServerProcess.return_value  # pylint: disable=protected-access
    return m


class TestServerMonitorStatus:
    def test_status_includes_expected_fields(self):
        m = _make_monitor()
        m._server.pid = 1234  # type: ignore[misc]  # pylint: disable=protected-access
        s = m.status()
        assert_that(s.pid).is_equal_to(1234)
        assert_that(s.failed_heartbeats).is_equal_to(0)
        assert_that(s.max_failed_heartbeats).is_greater_than(0)


class TestServerMonitorHeartbeat:
    def test_heartbeat_ok_resets_failed_count(self):
        m = _make_monitor()
        m._failed_heartbeats = 2  # pylint: disable=protected-access
        with patch("decker.server.monitor.API") as mock_api:
            healthy = DeckerServiceStatus(service_status=DeckerStatusEnum.HEALTHY, last_heartbeat=0.0)
            mock_api.request_as.side_effect = lambda t, fn, *a, **kw: healthy if fn == "heartbeat" else None
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(result).is_true()
        assert_that(m._failed_heartbeats).is_equal_to(0)  # pylint: disable=protected-access

    def test_heartbeat_failure_increments_count(self):
        m = _make_monitor()
        with patch("decker.server.monitor.API") as mock_api:
            mock_api.request_as.side_effect = ConnectionRefusedError("refused")
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(m._failed_heartbeats).is_equal_to(1)  # pylint: disable=protected-access
        assert_that(result).is_true()  # still under threshold (3)

    def test_heartbeat_fails_after_max_failures(self):
        m = _make_monitor()
        m._failed_heartbeats = 2  # pylint: disable=protected-access
        with patch("decker.server.monitor.API") as mock_api:
            mock_api.request_as.side_effect = ConnectionRefusedError("refused")
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(result).is_false()

    def test_unexpected_heartbeat_response_counts_as_failure(self):
        m = _make_monitor()
        with patch("decker.server.monitor.API") as mock_api:
            mock_api.request_as.return_value = None
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(m._failed_heartbeats).is_equal_to(1)  # pylint: disable=protected-access


class TestServerMonitorMemory:
    def test_memory_ok_returns_true_under_limit(self):
        m = _make_monitor()
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        m._memory_limit = 1024 * 1024 * 1024  # pylint: disable=protected-access
        with patch("decker.server.monitor._read_rss_bytes", return_value=100 * 1024 * 1024):
            result = m._memory_ok()  # pylint: disable=protected-access
        assert_that(result).is_true()

    def test_memory_ok_returns_false_over_limit(self):
        m = _make_monitor()
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        m._memory_limit = 100 * 1024 * 1024  # pylint: disable=protected-access
        with patch("decker.server.monitor._read_rss_bytes", return_value=200 * 1024 * 1024):
            result = m._memory_ok()  # pylint: disable=protected-access
        assert_that(result).is_false()

    def test_memory_ok_returns_true_when_no_pid(self):
        m = _make_monitor()
        m._server.pid = None  # type: ignore[misc]  # pylint: disable=protected-access
        assert_that(m._memory_ok()).is_true()  # pylint: disable=protected-access

    def test_memory_ok_returns_true_when_rss_unreadable(self):
        m = _make_monitor()
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        with patch("decker.server.monitor._read_rss_bytes", return_value=None):
            assert_that(m._memory_ok()).is_true()  # pylint: disable=protected-access


class TestServerMonitorCheckOnce:
    def test_check_once_sets_stop_requested_on_clean_exit(self):
        m = _make_monitor()
        m._server.is_running = False  # type: ignore[misc]  # pylint: disable=protected-access
        m._server.exited_cleanly = True  # type: ignore[misc]  # pylint: disable=protected-access
        m._check_once()  # pylint: disable=protected-access
        assert_that(m._stop_requested).is_true()  # pylint: disable=protected-access

    def test_check_once_restarts_on_unexpected_death(self):
        m = _make_monitor()
        m._server.is_running = False  # type: ignore[misc]  # pylint: disable=protected-access
        m._server.exited_cleanly = False  # type: ignore[misc]  # pylint: disable=protected-access
        m._server.start.return_value = True  # type: ignore[attr-defined]
        m._check_once()  # pylint: disable=protected-access
        m._server.stop.assert_called()  # type: ignore[attr-defined]

    def test_check_once_restarts_on_heartbeat_failure(self):
        m = _make_monitor()
        m._server.is_running = True  # type: ignore[misc]  # pylint: disable=protected-access
        m._failed_heartbeats = 3  # already at/past max  # pylint: disable=protected-access
        with patch("decker.server.monitor.API") as mock_api:
            mock_api.request_as.side_effect = ConnectionRefusedError("refused")
            m._check_once()  # pylint: disable=protected-access
        m._server.stop.assert_called()  # type: ignore[attr-defined]

    def test_check_once_restarts_on_memory_exceed(self):
        m = _make_monitor()
        m._server.is_running = True  # type: ignore[misc]  # pylint: disable=protected-access
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        m._memory_limit = 10  # pylint: disable=protected-access
        with (
            patch("decker.server.monitor.API") as mock_api,
            patch("decker.server.monitor._read_rss_bytes", return_value=999999999),
        ):
            mock_api.request_as.return_value = DeckerServiceStatus(
                service_status=DeckerStatusEnum.HEALTHY, last_heartbeat=0.0
            )
            m._check_once()  # pylint: disable=protected-access
        m._server.stop.assert_called()  # type: ignore[attr-defined]

    def test_restart_server_resets_failed_heartbeats(self):
        m = _make_monitor()
        m._failed_heartbeats = 5  # pylint: disable=protected-access
        m._server.start.return_value = True  # type: ignore[attr-defined]
        m._restart_server()  # pylint: disable=protected-access
        assert_that(m._failed_heartbeats).is_equal_to(0)  # pylint: disable=protected-access
