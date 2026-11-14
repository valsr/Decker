import asyncio
import json
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.plugin.elgato.bridge import ElgatoBridge
from decker.plugin.elgato.protocol import ElgatoEvent, serialize


def _make_bridge():
    return ElgatoBridge(MagicMock(), MagicMock())


class TestHandleMessage:
    def test_register_plugin_stores_connection(self):
        bridge = _make_bridge()
        connection = MagicMock()
        raw = serialize(ElgatoEvent(event="registerPlugin", payload={"pluginUUID": "com.elgato.test"}))

        result = bridge._handle_message(connection, raw, None)  # pylint: disable=protected-access

        assert_that(result).is_equal_to("com.elgato.test")
        assert_that(bridge._connections).contains_key("com.elgato.test")  # pylint: disable=protected-access

    def test_register_plugin_without_uuid_keeps_existing_plugin_uuid(self):
        bridge = _make_bridge()
        raw = serialize(ElgatoEvent(event="registerPlugin", payload={}))

        result = bridge._handle_message(MagicMock(), raw, "existing")  # pylint: disable=protected-access

        assert_that(result).is_equal_to("existing")

    def test_event_before_registration_is_ignored(self):
        bridge = _make_bridge()
        raw = serialize(ElgatoEvent(event="setTitle", payload={"title": "x"}))

        result = bridge._handle_message(MagicMock(), raw, None)  # pylint: disable=protected-access

        assert_that(result).is_none()

    def test_event_after_registration_dispatches_to_translator(self):
        bridge = _make_bridge()
        raw = serialize(ElgatoEvent(event="setTitle", action="com.elgato.test.show", payload={"title": "x"}))

        result = bridge._handle_message(MagicMock(), raw, "com.elgato.test")  # pylint: disable=protected-access

        assert_that(result).is_equal_to("com.elgato.test")
        bridge._translator._sink.set_title.assert_called_once()  # pylint: disable=protected-access


class TestSendToPlugin:
    @pytest.mark.asyncio
    async def test_warns_and_returns_when_no_connection(self):
        bridge = _make_bridge()
        await bridge.send_to_plugin("com.elgato.unknown", ElgatoEvent(event="keyDown"))  # should not raise

    @pytest.mark.asyncio
    async def test_sends_serialized_event_to_connection(self):
        bridge = _make_bridge()
        connection = MagicMock()
        connection.send = MagicMock(return_value=asyncio.sleep(0))
        bridge._connections["com.elgato.test"] = connection  # pylint: disable=protected-access

        await bridge.send_to_plugin("com.elgato.test", ElgatoEvent(event="keyDown"))

        connection.send.assert_called_once()


class TestLifecycle:
    def test_start_then_stop_does_not_raise(self):
        bridge = ElgatoBridge(MagicMock(), MagicMock(), port=0)
        bridge.start()
        try:
            assert _wait_for(lambda: bridge._server is not None)  # pylint: disable=protected-access
        finally:
            bridge.stop()


def _wait_for(predicate, timeout=2.0):
    import time  # pylint: disable=import-outside-toplevel

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _FakeConnection:
    def __init__(self, messages: list[str | bytes]) -> None:
        self._messages = messages

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for message in self._messages:
            yield message


class TestHandleConnection:
    @pytest.mark.asyncio
    async def test_malformed_message_does_not_drop_connection(self):
        bridge = _make_bridge()
        register = json.dumps({"event": "registerPlugin", "payload": {"pluginUUID": "com.elgato.test"}})
        seen: list[str] = []
        original = bridge._handle_message  # pylint: disable=protected-access

        def _record(connection, raw, plugin_uuid):
            seen.append(raw)
            return original(connection, raw, plugin_uuid)

        bridge._handle_message = _record  # pylint: disable=protected-access
        connection = _FakeConnection(["not json", b"\xff\xfe", register])

        await bridge._handle_connection(connection)  # pylint: disable=protected-access

        assert_that(seen).contains(register)
