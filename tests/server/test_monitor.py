"""Tests for the server monitor — focuses on the internal state-machine logic."""

from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.common.context import ServerAppContext
from decker.server.monitor import ServerMonitor, _connect_host
from decker.server.service import DeckerServiceStatus, DeckerStatusEnum


def _make_monitor() -> ServerMonitor:
    with patch("decker.server.monitor.config") as mock_cfg:
        mock_cfg.get_as.side_effect = lambda key, typ: {
            "server.host": "localhost",
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
        with patch.object(m, "_api") as mock_api:
            healthy = DeckerServiceStatus(service_status=DeckerStatusEnum.HEALTHY, last_heartbeat=0.0)
            mock_api.request_as.side_effect = lambda t, fn, *a, **kw: healthy if fn == "heartbeat" else None
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(result).is_true()
        assert_that(m._failed_heartbeats).is_equal_to(0)  # pylint: disable=protected-access

    def test_heartbeat_failure_increments_count(self):
        m = _make_monitor()
        with patch.object(m, "_api") as mock_api:
            mock_api.request_as.side_effect = ConnectionRefusedError("refused")
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(m._failed_heartbeats).is_equal_to(1)  # pylint: disable=protected-access
        assert_that(result).is_true()  # still under threshold (3)

    def test_heartbeat_fails_after_max_failures(self):
        m = _make_monitor()
        m._failed_heartbeats = 2  # pylint: disable=protected-access
        with patch.object(m, "_api") as mock_api:
            mock_api.request_as.side_effect = ConnectionRefusedError("refused")
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(result).is_false()

    def test_unexpected_heartbeat_response_counts_as_failure(self):
        m = _make_monitor()
        with patch.object(m, "_api") as mock_api:
            mock_api.request_as.return_value = None
            result = m._heartbeat_ok()  # pylint: disable=protected-access
        assert_that(m._failed_heartbeats).is_equal_to(1)  # pylint: disable=protected-access


class TestServerMonitorMemory:
    def test_memory_ok_returns_true_under_limit(self):
        m = _make_monitor()
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        m._memory_limit = 1024 * 1024 * 1024  # pylint: disable=protected-access
        with patch("decker.server.monitor.rss_bytes", return_value=100 * 1024 * 1024):
            result = m._memory_ok()  # pylint: disable=protected-access
        assert_that(result).is_true()

    def test_memory_ok_returns_false_over_limit(self):
        m = _make_monitor()
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        m._memory_limit = 100 * 1024 * 1024  # pylint: disable=protected-access
        with patch("decker.server.monitor.rss_bytes", return_value=200 * 1024 * 1024):
            result = m._memory_ok()  # pylint: disable=protected-access
        assert_that(result).is_false()

    def test_memory_ok_returns_true_when_no_pid(self):
        m = _make_monitor()
        m._server.pid = None  # type: ignore[misc]  # pylint: disable=protected-access
        assert_that(m._memory_ok()).is_true()  # pylint: disable=protected-access

    def test_memory_ok_returns_true_when_rss_unreadable(self):
        m = _make_monitor()
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        with patch("decker.server.monitor.rss_bytes", return_value=None):
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
        with patch.object(m, "_api") as mock_api:
            mock_api.request_as.side_effect = ConnectionRefusedError("refused")
            m._check_once()  # pylint: disable=protected-access
        m._server.stop.assert_called()  # type: ignore[attr-defined]

    def test_check_once_restarts_on_memory_exceed(self):
        m = _make_monitor()
        m._server.is_running = True  # type: ignore[misc]  # pylint: disable=protected-access
        m._server.pid = 12345  # type: ignore[misc]  # pylint: disable=protected-access
        m._memory_limit = 10  # pylint: disable=protected-access
        with (
            patch.object(m, "_api") as mock_api,
            patch("decker.server.monitor.rss_bytes", return_value=999999999),
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

    def test_restart_server_drops_cached_api_connection(self):
        m = _make_monitor()
        m._api = MagicMock()  # pylint: disable=protected-access
        m._server.start.return_value = True  # type: ignore[attr-defined]
        m._restart_server()  # pylint: disable=protected-access
        m._api.close.assert_called_once()  # pylint: disable=protected-access

    def test_heartbeat_targets_configured_port(self):
        with patch("decker.server.monitor.config") as mock_cfg:
            mock_cfg.get_as.side_effect = lambda key, typ: {
                "server.host": "0.0.0.0",
                "server.port": 19999,
                "server.startup_wait": 5.0,
                "server.health_check_interval": 5.0,
                "server.max_failed_heartbeats": 3,
                "server.memory_limit": 1024,
            }[key]
            with patch("decker.server.monitor.ServerProcess"):
                m = ServerMonitor(ServerAppContext())
        assert_that(m._api.port).is_equal_to(19999)  # pylint: disable=protected-access
        assert_that(m._api.host).is_equal_to("localhost")  # pylint: disable=protected-access


class TestConnectHost:
    @pytest.mark.parametrize(
        "bind,expected",
        [
            ("0.0.0.0", "localhost"),
            ("", "localhost"),
            ("::", "localhost"),
            ("localhost", "localhost"),
            ("192.168.1.5", "192.168.1.5"),
        ],
    )
    def test_maps_wildcard_bind_addresses_to_localhost(self, bind, expected):
        assert_that(_connect_host(bind)).is_equal_to(expected)


class _FakeServer:
    """Stands in for ServerProcess: records its construction and whether starting it succeeds."""

    instances: list["_FakeServer"] = []
    start_results: list[bool] = []

    def __init__(self, port, startup_wait, app_context, host="localhost") -> None:
        self.port = port
        self.host = host
        self.started = False
        self.is_running = False
        self.exit_code = None
        self.exited_cleanly = False
        self.pid = None
        _FakeServer.instances.append(self)

    def start(self) -> bool:
        ok = _FakeServer.start_results.pop(0) if _FakeServer.start_results else True
        self.started = ok
        self.is_running = ok
        return ok

    def stop(self) -> bool:
        self.is_running = False
        return True


@pytest.fixture()
def restart_env(isolated_config):
    """A monitor whose server child asked for a restart (exit code 75) after the port was changed in config."""
    from decker.server.reconfigure import RESTART_EXIT_CODE
    from decker.server.settings import read_settings

    _FakeServer.instances = []
    _FakeServer.start_results = []
    m = _make_monitor()
    m._good = read_settings()  # pylint: disable=protected-access
    isolated_config.set("server.host", "localhost")
    m._server.is_running = False  # type: ignore[misc]  # pylint: disable=protected-access
    m._server.exit_code = RESTART_EXIT_CODE  # type: ignore[misc]  # pylint: disable=protected-access
    m._server.exited_cleanly = False  # type: ignore[misc]  # pylint: disable=protected-access
    healthy = DeckerServiceStatus(service_status=DeckerStatusEnum.HEALTHY, last_heartbeat=0.0)
    api_cls = MagicMock()
    api_cls.return_value.request_as.return_value = healthy
    with patch("decker.server.monitor.ServerProcess", _FakeServer), patch("decker.server.monitor.ApiHandler", api_cls):
        yield m, isolated_config, api_cls


class TestServerMonitorReconfiguration:
    def test_restart_request_rebuilds_with_the_new_port_and_memory_limit(self, restart_env):
        m, cfg, api_cls = restart_env
        cfg.set("server.port", 19000)
        cfg.set("server.memory_limit", 256 * 1024 * 1024)

        m._check_once()  # pylint: disable=protected-access

        assert_that(_FakeServer.instances).is_length(1)
        assert_that(_FakeServer.instances[0].port).is_equal_to(19000)
        assert_that(_FakeServer.instances[0].started).is_true()
        assert_that(api_cls.call_args.kwargs["port"]).is_equal_to(19000)
        assert_that(m._memory_limit).is_equal_to(256 * 1024 * 1024)  # pylint: disable=protected-access
        assert_that(m._good.port).is_equal_to(19000)  # pylint: disable=protected-access

    def test_failed_start_rolls_back_to_the_last_good_settings(self, restart_env):
        m, cfg, _ = restart_env
        cfg.set("server.port", 19000)
        _FakeServer.start_results = [False, True]

        m._check_once()  # pylint: disable=protected-access

        assert_that([s.port for s in _FakeServer.instances]).is_equal_to([19000, 18861])
        assert_that(_FakeServer.instances[1].started).is_true()
        assert_that(cfg.get_as("server.port", int)).is_equal_to(18861)
        assert_that(cfg.get_as("server.last_apply_error", str)).contains("19000")
        assert_that(m._good.port).is_equal_to(18861)  # pylint: disable=protected-access

    def test_unhealthy_new_server_is_rolled_back_too(self, restart_env):
        m, cfg, api_cls = restart_env
        cfg.set("server.port", 19000)
        cfg.set("server.apply_timeout", 0.3)
        api_cls.return_value.request_as.return_value = None

        with patch("decker.server.monitor.time.sleep"):
            m._check_once()  # pylint: disable=protected-access

        assert_that(cfg.get_as("server.port", int)).is_equal_to(18861)
        assert_that(cfg.get_as("server.last_apply_error", str)).is_not_empty()

    def test_exit_code_zero_still_stops_the_monitor_without_rebuilding(self, restart_env):
        m, cfg, _ = restart_env
        cfg.set("server.port", 19000)
        m._server.exit_code = 0  # type: ignore[misc]  # pylint: disable=protected-access
        m._server.exited_cleanly = True  # type: ignore[misc]  # pylint: disable=protected-access

        m._check_once()  # pylint: disable=protected-access

        assert_that(m._stop_requested).is_true()  # pylint: disable=protected-access
        assert_that(_FakeServer.instances).is_empty()
