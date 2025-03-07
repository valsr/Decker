from assertpy import assert_that

from decker_server.config import Config  # see: Config and related exceptions
from decker_server.config import (ConfigurationKeyExists,
                                  InvalidConfigurationValue, decode_value)


class DummyBackend:
    """A dummy backend for testing purposes.

    This class simulates loading from and saving to a backend storage.
    """

    def __init__(self):
        # Given: an empty in-memory data storage
        self.data = {}

    def load(self) -> dict:
        # When: loading data from the backend
        return self.data

    def save(self, data: dict) -> None:
        # Then: updating in-memory storage with provided data
        self.data = data


# <see: TestLoadSave> ---------------------------------------------------------
class TestLoadSave:
    """Tests for validating the load and save methods of Config.

    See:
        Config.load, Config.save
    """

    def test_load_and_save(self):
        # Given: a dummy backend and a configuration instance with specific data
        backend = DummyBackend()
        initial_data = {"FOO": "bar", "nested": {"key": "value"}}
        backend.data = initial_data.copy()
        config_obj = Config(backend)

        # When: loading the configuration from the backend
        config_obj.load()

        # Then: internal data should be flattened with lowercase keys
        expected_flat = {"foo": "bar", "nested.key": "value"}
        assert_that(config_obj._data).is_equal_to(expected_flat)

        # Given: update the internal data
        config_obj._data["new.key"] = "new_value"

        # When: saving the configuration to the backend
        config_obj.save()

        # Then: the backend data should be unflattened
        expected_unflattened = {"foo": "bar", "nested": {"key": "value"},
                                  "new": {"key": "new_value"}}
        assert_that(backend.data).is_equal_to(expected_unflattened)


# <see: TestHasGet__getitem> --------------------------------------------------
class TestHasGet:
    """Tests for the has, get, and __getitem__ methods of Config.

    See:
        Config.has, Config.get, Config.__getitem__
    """

    def test_has_and_get_existing_key(self):
        # Given: a dummy backend with preloaded flattened data and a configuration instance
        backend = DummyBackend()
        backend.data = {"foo": "bar"}
        config_obj = Config(backend)
        config_obj.load()
        config_obj._data = {"test.key": "value"}  # simulate preloaded data

        # When: checking for existence and retrieving the value for an existing key
        exists = config_obj.has("test.key")
        value = config_obj.get("test.key")
        value_item = config_obj["test.key"]

        # Then: the key should exist and the retrieved value should match
        assert_that(exists).is_true()
        assert_that(value).is_equal_to("value")
        assert_that(value_item).is_equal_to("value")

    def test_get_nonexistent_key_raises_keyerror(self):
        # Given: a configuration instance with empty data
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {}

        # When/Then: accessing a non-existent key via __getitem__ should raise KeyError
        try:
            _ = config_obj["nonexistent"]
            assert False, "Expected KeyError"
        except KeyError as e:
            assert_that(str(e)).contains("nonexistent")


# <see: TestSet> --------------------------------------------------------------
class TestSet:
    """Tests for validating the set and __setitem__ methods of Config.

    See:
        Config.set, Config.__setitem__
    """

    def test_set_valid_value(self):
        # Given: a dummy backend and a configuration instance without the key conflict
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {}

        # When: setting a valid configuration key with a valid type (string)
        config_obj.set("Test.Key", "value")

        # Then: the key should be stored in lowercase and retrievable
        assert_that(config_obj.get("test.key")).is_equal_to("value")
        # And: backend storage should reflect the change through flattening/unflattening
        expected_backend = {"test": {"key": "value"}}
        assert_that(backend.data).is_equal_to(expected_backend)

    def test_set_invalid_value_raises_exception(self):
        # Given: a dummy backend and a configuration instance without data
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {}

        # When/Then: setting a key with an invalid type (e.g., dict) should raise InvalidConfigurationValue
        try:
            config_obj.set("invalid.key", {"not": "allowed"})
            assert False, "Expected InvalidConfigurationValue"
        except InvalidConfigurationValue as e:
            assert_that(str(e)).contains("Value for invalid.key")

    def test_set_conflict_raises_configuration_key_exists(self):
        # Given: a dummy backend and a configuration instance with an existing parent key
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {"test": "parent_value"}

        # When/Then: setting a sub-key when a parent key exists should raise
        try:
            config_obj.set("test.key", "value")
            assert False, "Expected ConfigurationKeyExists"
        except ConfigurationKeyExists as e:
            assert_that(str(e)).contains("parent key test")


# <see: TestUnset> ------------------------------------------------------------
class TestUnset:
    """Tests for validating the unset method of Config.

    See:
        Config.unset
    """

    def test_unset_existing_keys(self):
        # Given: a dummy backend and a configuration instance with multiple keys
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {"test.key": "value", "test.other": "value2", "another": "val"}

        # When: unsetting keys with the prefix 'test'
        config_obj.unset("test")

        # Then: only keys that do not match the prefix should remain and backend should be updated
        remaining_keys = list(config_obj._data.keys())
        assert_that(remaining_keys).contains_only("another")
        expected_backend = {"another": "val"}
        assert_that(backend.data).is_equal_to(expected_backend)

    def test_unset_nonexistent_key(self):
        # Given: a configuration instance with some keys
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {"key": "value"}

        # When: unsetting a key that does not exist
        config_obj.unset("nonexistent")

        # Then: the data remains unchanged and backend is not updated (remains same as previously saved)
        assert_that(config_obj._data).is_equal_to({"key": "value"})
        # Because save is only triggered if a removal happens,
        # backend.data remains unchanged (initially empty in dummy, but reflecting no save)
        assert_that(backend.data).is_not_equal_to({"key": "value"})


# <see: TestList> -------------------------------------------------------------
class TestList:
    """Tests for validating the list method of Config.

    See:
        Config.list
    """

    def test_list_all_entries(self):
        # Given: a configuration instance with multiple entries
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {"a": 1, "b.c": 2, "d": 3}

        # When: listing all entries without filtering
        result = config_obj.list()

        # Then: all key-value pairs should be returned
        expected = [("a", 1), ("b.c", 2), ("d", 3)]
        assert_that(result).is_equal_to(expected)

    def test_list_filtered_entries(self):
        # Given: a configuration instance with entries having nested keys
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {"a": 1, "a.b": 2, "a.b.c": 3, "d": 4}

        # When: listing entries filtered by key 'a.b'
        result = config_obj.list("a.b")

        # Then: only keys that are exactly 'a.b' or start with 'a.b.' are returned
        expected = [("a.b", 2), ("a.b.c", 3)]
        assert_that(result).is_equal_to(expected)


# <see: TestFind> -------------------------------------------------------------
class TestFind:
    """Tests for validating the find method of Config.

    See:
        Config.find
    """

    def test_find_with_callback(self):
        # Given: a configuration instance with various entries
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {"alpha": 1, "beta": 2, "gamma": 3}

        # When: using find with a callback that returns True for even values
        result = list(config_obj.find(lambda k, v: v % 2 == 0))

        # Then: only the key-value pair with an even value should be returned
        expected = [("beta", 2)]
        assert_that(result).is_equal_to(expected)

    def test_find_with_non_callable_raises_exception(self):
        # Given: a configuration instance with some entries
        backend = DummyBackend()
        config_obj = Config(backend)
        config_obj._data = {"a": 1}

        # When/Then: invoking find with a non-callable should raise TypeError
        try:
            list(config_obj.find("not a callable"))
            assert False, "Expected TypeError"
        except TypeError as e:
            assert_that(str(e)).contains("callback must be a callable function")

class TestDecodeValue:
    """Tests for validating the decode_value function.

    See: decode_value
    """

    def test_decode_bytes(self):
        # Given: a bytes value representing a valid UTF-8 string
        value = b"hello world"

        # When: calling decode_value on the bytes value
        result = decode_value(value)

        # Then: the returned string should match the decoded value from UTF-8
        assert_that(result).is_equal_to("hello world")

    def test_decode_non_bytes_numeric(self):
        # Given: a non-bytes numeric value
        value = 123

        # When: calling decode_value on the numeric value
        result = decode_value(value)

        # Then: the returned string should be the string representation of the number
        assert_that(result).is_equal_to("123")

    def test_decode_non_bytes_string(self):
        # Given: a non-bytes string value
        value = "already_string"

        # When: calling decode_value on the string value
        result = decode_value(value)

        # Then: the returned string should be identical to the original string
        assert_that(result).is_equal_to("already_string")
