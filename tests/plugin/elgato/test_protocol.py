import json

import pytest
from assertpy import assert_that

from decker.plugin.elgato.protocol import ElgatoEvent, deserialize, serialize


class TestSerialize:
    def test_includes_only_set_fields(self):
        raw = serialize(ElgatoEvent(event="keyDown"))
        assert_that(json.loads(raw)).is_equal_to({"event": "keyDown"})

    def test_includes_context_action_and_payload(self):
        event = ElgatoEvent(event="setTitle", context="ctx-1", action="com.decker.test.show", payload={"title": "x"})
        raw = serialize(event)
        assert_that(json.loads(raw)).is_equal_to(
            {"event": "setTitle", "context": "ctx-1", "action": "com.decker.test.show", "payload": {"title": "x"}}
        )


class TestDeserialize:
    def test_roundtrips_through_serialize(self):
        event = ElgatoEvent(event="keyDown", context="ctx-1", payload={"settings": {}})
        assert_that(deserialize(serialize(event))).is_equal_to(event)

    def test_missing_event_field_raises(self):
        with pytest.raises(ValueError):
            deserialize(json.dumps({"context": "ctx-1"}))

    def test_non_object_json_raises(self):
        with pytest.raises(ValueError):
            deserialize(json.dumps([1, 2, 3]))

    def test_optional_fields_default_to_none(self):
        event = deserialize(json.dumps({"event": "keyDown"}))
        assert_that(event.context).is_none()
        assert_that(event.action).is_none()
        assert_that(event.payload).is_none()
