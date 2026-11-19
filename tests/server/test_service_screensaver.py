import base64
import io
import json
import threading
import time

import pytest
import rpyc
from assertpy import assert_that
from PIL import Image

from decker.common.model import ScreensaverSettings
from decker.server import service as service_module
from decker.server.screensaver.settings import settings_to_json
from decker.server.server import NoDelayThreadedServer
from decker.server.service import DeckerService
from tests.server.screensaver.screensaver_fixture import (
    COLS,
    DEV,
    PX,
    ROWS,
    saver_context,
)


@pytest.fixture(name="stack")
def stack_fixture(tmp_path):
    with saver_context(tmp_path) as (ctx, devices):
        DeckerService.configure_context(ctx)
        try:
            yield ctx, devices
        finally:
            DeckerService._context = None  # pylint: disable=protected-access


@pytest.fixture(name="server")
def server_fixture(stack):
    server = NoDelayThreadedServer(
        DeckerService, hostname="localhost", port=0, protocol_config={"allow_public_attrs": True}
    )
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    time.sleep(0.3)
    yield server
    server.close()
    thread.join(2)


@pytest.fixture(name="conn")
def conn_fixture(server):
    connection = rpyc.utils.factory.connect("localhost", server.port)
    yield connection
    connection.close()


def _json(**changes) -> str:
    return settings_to_json(ScreensaverSettings(**changes))


def _service(remote: bool = False) -> DeckerService:
    svc = DeckerService()
    svc._peer_host = "10.1.2.3" if remote else "127.0.0.1"  # pylint: disable=protected-access
    return svc


def test_get_set_round_trip_over_a_real_socket(conn):
    assert_that(json.loads(conn.root.screensaver_set(DEV, _json(timeout_minutes=9)))).is_true()

    result = json.loads(conn.root.screensaver_get(DEV))

    assert_that(result).contains_entry(**{"timeout_minutes": 9, "active": False, "last_error": ""})


def test_remote_set_with_path_refused(server, monkeypatch, tmp_path):
    monkeypatch.setattr(service_module, "_peer_host", lambda _conn: "203.0.113.5")  # as seen at connect time
    conn = rpyc.utils.factory.connect("localhost", server.port)
    image = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(image)

    with pytest.raises(PermissionError):
        conn.root.screensaver_set(DEV, _json(content="image", image_path=str(image)))
    assert_that(json.loads(conn.root.screensaver_set(DEV, _json(brightness=50)))).is_true()

    assert_that(json.loads(conn.root.screensaver_get(DEV))).contains_entry(**{"brightness": 50, "image_path": ""})
    conn.close()


def test_failures_do_not_break_the_service(conn):
    with pytest.raises(ValueError, match="unknown device"):
        conn.root.screensaver_get("nope")
    with pytest.raises(ValueError, match="brightness"):
        conn.root.screensaver_set(DEV, _json().replace('"brightness": 100', '"brightness": 0'))

    assert_that(json.loads(conn.root.screensaver_get(DEV))["brightness"]).is_equal_to(100)


def test_local_service_may_set_a_path(stack, tmp_path):
    image = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(image)

    result = _service().screensaver_set(DEV, _json(content="image", image_path=str(image)))

    assert_that(json.loads(result)).is_true()
    assert_that(stack[0].screensaver_store.get(DEV).image_path).is_equal_to(str(image))


def test_remote_service_refuses_a_path(stack):
    with pytest.raises(PermissionError):
        _service(remote=True).screensaver_set(DEV, _json(content="image", image_path="/x.png"))
    assert_that(stack[0].screensaver_store.get(DEV).image_path).is_empty()


def test_preview_returns_png(conn):
    result = json.loads(conn.root.screensaver_preview(DEV, _json()))

    with Image.open(io.BytesIO(base64.b64decode(result))) as image:
        assert_that(image.format).is_equal_to("PNG")
        assert_that(image.size).is_equal_to((COLS * PX, ROWS * PX))


def test_activate_and_deactivate_rpcs_flip_status(conn):
    assert_that(json.loads(conn.root.screensaver_activate(DEV))).is_true()
    assert_that(json.loads(conn.root.screensaver_get(DEV))["active"]).is_true()
    assert_that(json.loads(conn.root.screensaver_deactivate(DEV))).is_true()
    assert_that(json.loads(conn.root.screensaver_get(DEV))["active"]).is_false()
    assert_that(json.loads(conn.root.screensaver_deactivate(DEV))).is_false()


def test_rpcs_without_a_context_raise_instead_of_crashing():
    DeckerService._context = None  # pylint: disable=protected-access

    with pytest.raises(RuntimeError, match="not available"):
        DeckerService().screensaver_get(DEV)
