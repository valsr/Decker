"""The RPC server must answer promptly: rpyc's ThreadPoolServer adds ~200 ms to every request and reply."""

import socket
import threading
import time

import pytest
import rpyc.utils.factory
from assertpy import assert_that
from rpyc.core.protocol import Connection
from rpyc.core.service import Service
from rpyc.utils.server import ThreadedServer

from decker.server.server import NoDelayThreadedServer


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
