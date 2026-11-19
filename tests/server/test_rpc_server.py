"""The RPC server must answer promptly: rpyc's ThreadPoolServer adds ~200 ms to every request and reply."""

import json
import socket
import threading
import time
from unittest.mock import MagicMock

import pytest
import rpyc.utils.factory
from assertpy import assert_that
from rpyc.core.protocol import Connection
from rpyc.core.service import Service
from rpyc.utils.server import ThreadedServer

from decker.server.app_rule_controller import AppRuleController
from decker.server.app_rule_store import AppRuleStore
from decker.server.device_state_store import DeviceStateStore
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.page_controller import PageController
from decker.server.pages import PageStore
from decker.server.server import NoDelayThreadedServer
from decker.server.server_context import ServerContext
from decker.server.service import DeckerService


class _Service(Service):
    def exposed_ping(self) -> str:
        return "ok"


@pytest.fixture(name="server")
def server_fixture():
    server = NoDelayThreadedServer(_Service, hostname="localhost", port=0, protocol_config={"allow_public_attrs": True})
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield server
    server.close()
    thread.join(2)


def _average_ms(conn: Connection, calls: int = 10) -> float:
    conn.root.ping()
    start = time.perf_counter()
    for _ in range(calls):
        conn.root.ping()
    return (time.perf_counter() - start) / calls * 1000


def test_a_request_round_trip_takes_milliseconds_not_hundreds_of_them(server) -> None:
    conn = rpyc.utils.factory.connect("localhost", server.port)

    assert_that(_average_ms(conn)).is_less_than(20)
    conn.close()


def test_serves_several_clients_at_once(server) -> None:
    first = rpyc.utils.factory.connect("localhost", server.port)
    second = rpyc.utils.factory.connect("localhost", server.port)

    assert_that(first.root.ping()).is_equal_to("ok")
    assert_that(second.root.ping()).is_equal_to("ok")
    first.close()
    second.close()


def test_accepted_sockets_disable_nagle(server, monkeypatch) -> None:
    seen: list[int] = []

    def record(_self, sock: socket.socket) -> None:
        seen.append(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))

    monkeypatch.setattr(ThreadedServer, "_authenticate_and_serve_client", record)
    conn = socket.create_connection(("localhost", server.port))
    deadline = time.time() + 2
    while not seen and time.time() < deadline:
        time.sleep(0.01)
    conn.close()

    assert_that(seen).is_length(1)
    assert_that(seen[0]).is_not_zero()


@pytest.fixture(name="rules_conn")
def rules_conn_fixture(tmp_path):
    db = tmp_path / "decker.db"
    pages, keys, states = PageStore(db_path=db), KeyAssignmentStore(db_path=db), DeviceStateStore(data_dir=tmp_path)
    store, controller = AppRuleStore(db_path=db), AppRuleController()
    ctx = ServerContext(
        device_manager=MagicMock(),
        plugin_manager=MagicMock(),
        key_assignment_store=keys,
        device_state_store=states,
        page_store=pages,
        page_controller=PageController(),
        event_bus=MagicMock(),
        app_rule_store=store,
        app_rule_controller=controller,
    )
    managers = (pages, keys, states, store, ctx.page_controller, controller)
    for manager in managers:
        manager.create(ctx)
    DeckerService.configure_context(ctx)
    server = NoDelayThreadedServer(
        DeckerService, hostname="localhost", port=0, protocol_config={"allow_public_attrs": True}
    )
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.3)
    conn = rpyc.utils.factory.connect("localhost", server.port)  # type: ignore[attr-defined]
    yield conn
    conn.close()
    server.close()
    thread.join(2)
    DeckerService._context = None  # pylint: disable=protected-access
    for manager in reversed(managers):
        manager.destroy()


def test_app_rules_round_trip_over_a_real_socket(rules_conn) -> None:
    rule = {
        "rule_id": "",
        "name": "Browser \u00e9\u4e2d",
        "enabled": True,
        "conditions": [
            {"field": "title", "op": "contains", "value": "caf\u00e9 \u4e2d\u6587"},
            {"field": "window_class", "op": "equals", "value": "firefox"},
        ],
        "profile_id": 0,
        "page_id": "",
    }

    stored = json.loads(rules_conn.root.app_rule_add("dev1", rule))
    assert_that(stored["rule_id"]).is_not_empty()
    assert_that(stored["conditions"][0]["value"]).is_equal_to("caf\u00e9 \u4e2d\u6587")

    stored["name"] = "Renamed"
    stored["conditions"][1]["value"] = "kate"
    assert_that(json.loads(rules_conn.root.app_rule_update("dev1", stored))).is_true()

    listed = json.loads(rules_conn.root.app_rules_list("dev1"))["rules"]
    assert_that(listed).is_length(1)
    assert_that(listed[0]["name"]).is_equal_to("Renamed")
    assert_that(listed[0]["conditions"][0]["value"]).is_equal_to("caf\u00e9 \u4e2d\u6587")
    assert_that(listed[0]["conditions"][1]["value"]).is_equal_to("kate")


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "no other keys"},
        {"name": "x", "enabled": True, "conditions": "nope", "profile_id": 0},
        {"name": "x", "enabled": True, "conditions": [{"field": "title"}], "profile_id": 0},
        {"name": "x", "enabled": True, "conditions": [], "profile_id": "zero"},
        {"name": "x", "enabled": True, "conditions": [], "profile_id": 0, "page_id": 5},
    ],
)
def test_malformed_rules_return_failure_over_a_real_socket(rules_conn, bad) -> None:
    assert_that(json.loads(rules_conn.root.app_rule_add("dev1", bad))).is_none()
    assert_that(json.loads(rules_conn.root.app_rule_update("dev1", bad))).is_false()
