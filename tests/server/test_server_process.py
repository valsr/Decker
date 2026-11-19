"""Integration tests that run the real server child process (the monitor tests mock ServerProcess)."""

import json
import multiprocessing
import socket
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from assertpy import assert_that

from decker.common import config
from decker.common import paths as decker_paths
from decker.common.api import ApiHandler
from decker.common.context import ServerAppContext
from decker.server.monitor import ServerMonitor
from decker.server.reconfigure import RESTART_EXIT_CODE
from decker.server.server import ServerProcess
from decker.server.service import DeckerServiceStatus, DeckerStatusEnum
from decker.server.settings import read_settings

_HEALTHY_DEADLINE = 120.0
_STOP_TIMEOUT = 60.0
_SKIP_REASON = (
    "real Stream Deck attached (docs/platform-support.md row 'Server and monitor'): "
    "the real server child would open it"
)


def _deck_attached() -> bool:
    try:
        from StreamDeck.DeviceManager import (  # pylint: disable=import-outside-toplevel
            DeviceManager,
        )

        return len(DeviceManager().enumerate()) > 0
    except Exception:  # pylint: disable=broad-except
        return False


@pytest.fixture(autouse=True)
def _no_real_hardware() -> None:
    if _deck_attached():
        pytest.skip(_SKIP_REASON)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(name="port")
def _port_fixture(tmp_path: Path) -> Iterator[int]:
    """Point all paths and the config at a temporary prefix and a free port; restore afterwards."""
    previous = decker_paths.home().parent
    decker_paths.configure(tmp_path)
    port = _free_port()
    config.set("server.host", "127.0.0.1")
    config.set("server.port", port)
    config.set("server.startup_wait", 1.0)
    config.set("server.stop_timeout", _STOP_TIMEOUT)
    config.set("plugin.update_check", "manual")
    try:
        yield port
    finally:
        decker_paths.configure(previous)


def _is_healthy(api: ApiHandler) -> bool:
    try:
        status = api.request_as(DeckerServiceStatus, "heartbeat")
    except Exception:  # pylint: disable=broad-except
        return False
    return status is not None and status.service_status == DeckerStatusEnum.HEALTHY


def _wait_healthy(port: int, server: ServerProcess) -> None:
    api = ApiHandler(host="127.0.0.1", port=port, timeout=5.0)
    deadline = time.monotonic() + _HEALTHY_DEADLINE
    try:
        while time.monotonic() < deadline:
            if _is_healthy(api):
                return
            assert_that(server.is_running).described_as("server child died before becoming healthy").is_true()
            api.close()
            time.sleep(0.25)
    finally:
        api.close()
    pytest.fail(f"server did not become healthy within {_HEALTHY_DEADLINE} s")


def _make_server(port: int, prefix: Path, startup_wait: float = 1.0) -> ServerProcess:
    return ServerProcess(port, startup_wait, ServerAppContext(prefix=prefix), host="127.0.0.1")


@pytest.fixture(name="server")
def _server_fixture(port: int, tmp_path: Path) -> Iterator[ServerProcess]:
    server = _make_server(port, tmp_path)
    try:
        yield server
    finally:
        server.stop()


def _child(server: ServerProcess) -> multiprocessing.Process:
    child = server._process  # pylint: disable=protected-access
    assert child is not None
    return child


def test_graceful_stop_of_the_real_server_exits_with_code_zero(server: ServerProcess, port: int) -> None:
    assert_that(server.start()).is_true()
    _wait_healthy(port, server)
    child = _child(server)

    assert_that(server.stop()).is_true()

    assert_that(child.is_alive()).is_false()
    assert_that(child.exitcode).is_equal_to(0)


def test_a_restart_needing_settings_change_makes_the_real_server_exit_with_the_restart_code(
    tmp_path: Path, port: int
) -> None:
    app_context = ServerAppContext(prefix=tmp_path, allow_client_reconfiguration=[])
    server = ServerProcess(port, 1.0, app_context, host="127.0.0.1")
    original = config.get_as("server.memory_limit", int)
    api = ApiHandler(host="127.0.0.1", port=port, timeout=5.0)
    try:
        assert_that(server.start()).is_true()
        _wait_healthy(port, server)
        child = _child(server)

        reply = api.request("server_settings_set", json.dumps({"memory_limit": 256 * 1024 * 1024}))
        child.join(timeout=_STOP_TIMEOUT)

        assert_that(json.loads(str(reply))["restarting"]).is_true()
        assert_that(child.is_alive()).is_false()
        assert_that(child.exitcode).is_equal_to(RESTART_EXIT_CODE)
    finally:
        api.close()
        server.stop()
        config.reload()
        config.set("server.memory_limit", original)


def test_a_port_that_is_already_in_use_rolls_back_to_the_old_port(tmp_path: Path, port: int) -> None:
    monitor = ServerMonitor(ServerAppContext(prefix=tmp_path, allow_client_reconfiguration=[]))
    api = ApiHandler(host="127.0.0.1", port=port, timeout=5.0)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    blocked_port = int(blocker.getsockname()[1])
    config.set("server.apply_timeout", 30.0)
    try:
        assert_that(monitor._server.start()).is_true()  # pylint: disable=protected-access
        _wait_healthy(port, monitor._server)  # pylint: disable=protected-access
        monitor._good = read_settings()  # pylint: disable=protected-access
        child = _child(monitor._server)  # pylint: disable=protected-access

        api.request("server_settings_set", json.dumps({"port": blocked_port}))
        child.join(timeout=_STOP_TIMEOUT)
        monitor._check_once()  # pylint: disable=protected-access

        assert_that(config.get_as("server.port", int)).is_equal_to(port)
        assert_that(config.get_as("server.last_apply_error", str)).contains(str(blocked_port))
        _wait_healthy(port, monitor._server)  # pylint: disable=protected-access
    finally:
        api.close()
        blocker.close()
        monitor.stop()
        config.reload()
        config.unset("server.last_apply_error")
        config.unset("server.apply_timeout")


def test_the_server_stops_with_code_zero_when_the_last_client_leaves(server: ServerProcess, port: int) -> None:
    config.set("server.stop_when_last_client_leaves", True)
    config.set("server.stop_grace", 0.5)
    api = ApiHandler(host="127.0.0.1", port=port, timeout=5.0)
    monitor_like = ApiHandler(host="127.0.0.1", port=port, timeout=5.0)
    try:
        assert_that(server.start()).is_true()
        _wait_healthy(port, server)
        child = _child(server)

        assert_that(monitor_like.request("heartbeat")).is_not_none()  # stays connected, like the monitor
        assert_that(api.request("client_attached")).is_true()
        api.close()
        child.join(timeout=_STOP_TIMEOUT)

        assert_that(child.is_alive()).is_false()
        assert_that(child.exitcode).is_equal_to(0)
    finally:
        api.close()
        monitor_like.close()
        config.unset("server.stop_when_last_client_leaves")
        config.unset("server.stop_grace")


def test_stop_right_after_start_still_ends_the_process(tmp_path: Path, port: int) -> None:
    server = _make_server(port, tmp_path, startup_wait=0.05)
    try:
        assert_that(server.start()).is_true()
        child = _child(server)
        started = time.monotonic()

        assert_that(server.stop()).is_true()

        assert_that(time.monotonic() - started).is_less_than(_STOP_TIMEOUT)
        assert_that(child.is_alive()).is_false()
        assert_that(child.exitcode).is_equal_to(0)
    finally:
        server.stop()


def test_restart_after_a_stop_brings_the_server_back(server: ServerProcess, port: int) -> None:
    assert_that(server.start()).is_true()
    _wait_healthy(port, server)
    assert_that(server.stop()).is_true()

    assert_that(server.start()).is_true()
    _wait_healthy(port, server)

    assert_that(server.is_running).is_true()


def test_monitor_restart_keeps_the_monitor_running(port: int, tmp_path: Path) -> None:
    monitor = ServerMonitor(ServerAppContext(prefix=tmp_path))
    server = monitor._server  # pylint: disable=protected-access
    try:
        assert_that(server.start()).is_true()
        _wait_healthy(port, server)
        first_pid = server.pid

        monitor._restart_server()  # pylint: disable=protected-access
        _wait_healthy(port, server)

        assert_that(monitor._stop_requested).is_false()  # pylint: disable=protected-access
        assert_that(server.pid).is_not_none().is_not_equal_to(first_pid)
    finally:
        monitor.stop()
