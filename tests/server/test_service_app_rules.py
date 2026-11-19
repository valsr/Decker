import json
import time
from dataclasses import asdict
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest
from assertpy import assert_that

from decker.common.model import WindowInfo
from decker.server.app_rule_controller import AppRuleController
from decker.server.app_rule_engine import AppRuleEngine
from decker.server.app_rule_store import AppRuleStore
from decker.server.device_state_store import DeviceStateStore
from decker.server.event_bus import EventBus
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore
from decker.server.server import ServerProcess
from decker.server.server_context import ServerContext
from decker.server.service import DeckerService
from decker.server.window_watcher import WatcherTimings, WindowWatcher
from decker.server.window_wiring import build_window_watcher
from decker.server.windows.backend import BackendStatus
from decker.server.windows.select import select_backend

DEV = "dev1"
FIREFOX = WindowInfo(window_class="firefox", title="Secret tab", executable="/usr/bin/firefox")
FAST = WatcherTimings(debounce=0.01, retry_base=0.01, retry_cap=0.05, pick_timeout=5.0)


class FakeBackend:
    name = "fake"

    def __init__(self, supports_pick: bool = True) -> None:
        self.supports_pick = supports_pick
        self.on_change: Callable[[WindowInfo], None] | None = None
        self.pick_callback: Callable[[WindowInfo | None], None] | None = None

    def available(self) -> BackendStatus:
        return BackendStatus("active")

    def start(
        self, on_change: Callable[[WindowInfo], None], on_failure: Callable[[Exception], None] | None = None
    ) -> None:
        self.on_change = on_change

    def stop(self) -> None:
        self.on_change = None

    def pick(self, on_result: Callable[[WindowInfo | None], None]) -> None:
        self.pick_callback = on_result


class FakeConn:
    def __init__(self) -> None:
        self.received: list[tuple[str, dict]] = []
        self.root = MagicMock()
        self.root.on_server_event = lambda event, payload: self.received.append((event, json.loads(payload)))

    def events(self, name: str) -> list[dict]:
        return [payload for event, payload in self.received if event == name]


def _wait(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


@pytest.fixture(autouse=True)
def _direct_delivery():
    with patch("decker.server.event_bus.async_", side_effect=lambda method: method):
        yield
    DeckerService._context = None  # pylint: disable=protected-access


@pytest.fixture()
def context(tmp_path):
    db = tmp_path / "decker.db"
    pages, keys, states = PageStore(db_path=db), KeyAssignmentStore(db_path=db), DeviceStateStore(data_dir=tmp_path)
    store, controller, engine = AppRuleStore(db_path=db), AppRuleController(), AppRuleEngine()
    device_manager = MagicMock()
    device_manager.list_devices.return_value = []
    ctx = ServerContext(
        device_manager=device_manager,
        plugin_manager=MagicMock(),
        key_assignment_store=keys,
        device_state_store=states,
        page_store=pages,
        page_controller=PageController(),
        event_bus=EventBus(),
        app_rule_store=store,
        app_rule_controller=controller,
        app_rule_engine=engine,
    )
    managers = (pages, keys, states, store, ctx.page_controller, controller, engine)
    for manager in managers:
        manager.create(ctx)
    DeckerService.configure_context(ctx)
    yield ctx
    if ctx.window_watcher is not None:
        ctx.window_watcher.stop()
    for manager in reversed(managers):
        manager.destroy()


@pytest.fixture()
def backend(context) -> FakeBackend:
    fake = FakeBackend()
    context.window_watcher = build_window_watcher(context, fake, FAST)
    context.window_watcher.start()
    return fake


def _service(remote: bool = False, conn: FakeConn | None = None) -> DeckerService:
    service = DeckerService()
    service._peer_host = "10.1.2.3" if remote else "127.0.0.1"  # pylint: disable=protected-access
    service._conn = conn  # pylint: disable=protected-access
    return service


def _rule(profile_id: int, **overrides) -> dict:
    rule = {
        "rule_id": "",
        "name": "Browser",
        "enabled": True,
        "conditions": [{"field": "window_class", "op": "equals", "value": "firefox"}],
        "profile_id": profile_id,
        "page_id": "",
    }
    return {**rule, **overrides}


def test_rule_rpcs_round_trip(context):
    service = _service()
    profile = context.page_controller.add_profile(DEV).profile_id

    stored = json.loads(service.app_rule_add(DEV, _rule(profile)))
    listed = json.loads(service.app_rules_list(DEV))
    assert_that(stored["rule_id"]).is_not_empty()
    assert_that(listed["rules"]).is_length(1)
    assert_that(listed["rules"][0]["conditions"][0]["value"]).is_equal_to("firefox")

    assert_that(json.loads(service.app_rule_update(DEV, {**stored, "name": "Renamed"}))).is_true()
    second = json.loads(service.app_rule_add(DEV, _rule(profile, name="Second")))
    assert_that(json.loads(service.app_rule_move(DEV, second["rule_id"], 0))).is_true()
    names = [r["name"] for r in json.loads(service.app_rules_list(DEV))["rules"]]
    assert_that(names).is_equal_to(["Second", "Renamed"])

    assert_that(json.loads(service.app_default_rule_set(DEV, True, profile, ""))).is_true()
    assert_that(json.loads(service.app_rules_list(DEV))["default_rule"]["enabled"]).is_true()
    assert_that(json.loads(service.app_rule_delete(DEV, stored["rule_id"]))).is_true()
    assert_that(json.loads(service.app_rules_list(DEV))["rules"]).is_length(1)


def test_rule_rpc_rejects_invalid_rule(context):
    service = _service()

    assert_that(json.loads(service.app_rule_add(DEV, _rule(99)))).is_none()
    assert_that(json.loads(service.app_rule_add(DEV, {"name": "broken"}))).is_none()
    assert_that(
        json.loads(service.app_rule_add(DEV, _rule(0, conditions=[{"field": "nope", "op": "equals"}])))
    ).is_none()
    assert_that(json.loads(service.app_rule_update(DEV, _rule(0, rule_id="missing")))).is_false()
    assert_that(json.loads(service.app_default_rule_set(DEV, True, 99, ""))).is_false()
    assert_that(json.loads(service.app_default_rule_set(DEV, True, "x", ""))).is_false()
    assert_that(json.loads(service.app_rules_list(DEV))["rules"]).is_empty()


def test_rule_rpcs_without_context_are_harmless():
    DeckerService._context = None  # pylint: disable=protected-access
    service = _service()

    assert_that(json.loads(service.app_rules_list(DEV))).is_none()
    assert_that(json.loads(service.app_rule_add(DEV, _rule(0)))).is_none()
    assert_that(json.loads(service.window_detection_status())).is_none()
    assert_that(json.loads(service.window_pick())).is_false()


def test_status_redacts_title_for_remote_peer(context, backend):
    assert backend.on_change is not None
    backend.on_change(FIREFOX)

    local = json.loads(_service().window_detection_status())
    remote = json.loads(_service(remote=True).window_detection_status())

    assert_that(local["window"]["title"]).is_equal_to("Secret tab")
    assert_that(remote["window"]["title"]).is_equal_to("")
    assert_that(remote["window"]["window_class"]).is_equal_to("firefox")
    assert_that(remote["state"]).is_equal_to("active")


def test_window_focused_redacted_for_remote_client_only(context, backend):
    local, remote = FakeConn(), FakeConn()
    context.event_bus.register(local, loopback=True)
    context.event_bus.register(remote, loopback=False)
    assert backend.on_change is not None

    backend.on_change(FIREFOX)

    assert_that(local.events("window_focused")[0]["window"]["title"]).is_equal_to("Secret tab")
    assert_that(remote.events("window_focused")[0]["window"]["title"]).is_equal_to("")
    assert_that(remote.events("window_focused")[0]["window"]["window_class"]).is_equal_to("firefox")


def test_window_detection_changed_is_pushed_on_status_change(context):
    conn = FakeConn()
    context.event_bus.register(conn, loopback=False)
    fake = FakeBackend()
    context.window_watcher = build_window_watcher(context, fake, FAST)

    context.window_watcher.start()

    _wait(lambda: bool(conn.events("window_detection_changed")))
    assert_that(conn.events("window_detection_changed")[-1]["state"]).is_equal_to("active")


def test_window_pick_result_goes_only_to_caller(context, backend):
    caller, other = FakeConn(), FakeConn()
    context.event_bus.register(caller, loopback=True)
    context.event_bus.register(other, loopback=True)
    engine = MagicMock()
    context.app_rule_engine = engine

    assert_that(json.loads(_service(conn=caller).window_pick())).is_true()
    assert backend.pick_callback is not None
    backend.pick_callback(FIREFOX)

    assert_that(caller.events("window_picked")).is_equal_to([{"window": asdict(FIREFOX)}])
    assert_that(other.events("window_picked")).is_empty()
    engine.on_focus.assert_not_called()


def test_window_pick_result_is_redacted_for_remote_caller(context, backend):
    caller = FakeConn()
    context.event_bus.register(caller, loopback=False)

    _service(remote=True, conn=caller).window_pick()
    assert backend.pick_callback is not None
    backend.pick_callback(FIREFOX)

    assert_that(caller.events("window_picked")[0]["window"]["title"]).is_equal_to("")


def test_window_pick_cancelled_sends_null_window(context, backend):
    caller = FakeConn()
    context.event_bus.register(caller, loopback=True)

    _service(conn=caller).window_pick()
    assert backend.pick_callback is not None
    backend.pick_callback(None)

    assert_that(caller.events("window_picked")).is_equal_to([{"window": None}])


def test_window_pick_false_when_unsupported(context):
    context.window_watcher = build_window_watcher(context, FakeBackend(supports_pick=False), FAST)
    context.window_watcher.start()

    assert_that(json.loads(_service(conn=FakeConn()).window_pick())).is_false()


def test_server_without_desktop_session_reports_unavailable_and_rule_rpcs_work(context):
    backend = select_backend({}, "linux")
    context.window_watcher = build_window_watcher(context, backend, FAST)
    context.window_watcher.start()
    service = _service()

    status = json.loads(service.window_detection_status())
    stored = json.loads(service.app_rule_add(DEV, _rule(0)))

    assert_that(status["state"]).is_equal_to("unavailable")
    assert_that(status["window"]).is_none()
    assert_that(stored["rule_id"]).is_not_empty()
    assert_that(json.loads(service.window_pick())).is_false()


def test_focus_change_switches_profile_through_the_watcher(context, backend):
    context.device_manager.list_devices.return_value = [MagicMock(id=DEV)]
    context.device_manager.show_page.return_value = True
    profile = context.page_controller.add_profile(DEV).profile_id
    _service().app_rule_add(DEV, _rule(profile))
    assert backend.on_change is not None

    backend.on_change(FIREFOX)

    _wait(lambda: context.page_controller.active_profile_id(DEV) == profile)


def test_on_connect_registers_loopback_flag_and_connection():
    DeckerService._context = MagicMock()  # pylint: disable=protected-access
    service = DeckerService()
    conn = MagicMock()
    conn._channel.stream.sock.getpeername.return_value = ("10.1.2.3", 1234)  # pylint: disable=protected-access

    service.on_connect(conn)

    DeckerService._context.event_bus.register.assert_called_once_with(
        conn, loopback=False
    )  # pylint: disable=protected-access
    assert_that(service._conn).is_same_as(conn)  # pylint: disable=protected-access


def test_watcher_backend_failure_at_boot_leaves_detection_unavailable(context):
    class Exploding(FakeBackend):
        def start(
            self, on_change: Callable[[WindowInfo], None], on_failure: Callable[[Exception], None] | None = None
        ) -> None:
            raise RuntimeError("no compositor")

    with patch("decker.server.server.select_backend", return_value=Exploding()):
        ServerProcess(0, 0, MagicMock())._start_window_watcher(context)  # pylint: disable=protected-access

    status = json.loads(_service().window_detection_status())
    assert_that(status["state"]).is_equal_to("unavailable")


def test_watcher_construction_failure_is_survived(context):
    with patch("decker.server.server.select_backend", side_effect=RuntimeError("boom")):
        ServerProcess(0, 0, MagicMock())._start_window_watcher(context)  # pylint: disable=protected-access

    assert_that(context.window_watcher).is_none()
    assert_that(json.loads(_service().window_detection_status())).is_none()
