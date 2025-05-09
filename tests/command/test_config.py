from assertpy import assert_that

import decker.config
from decker.command import config as command_config


class TestListConfig:
    def test_list_config_no_items(self, monkeypatch, caplog):
        # Arrange
        def fake_find(filter_func):
            # Arrange: return no configuration items
            return []

        monkeypatch.setattr(decker.config, "find", fake_find)

        # Act
        command_config.list_config()

        # Assert
        assert_that(caplog.text).contains("No configuration items match the specified keywords.")

    def test_list_config_with_items_and_keywords(self, monkeypatch, capsys):
        # Arrange
        def fake_find(filter_func):
            # Arrange: list of configuration items (key, value)
            items = [("alpha", "A"), ("beta", "B"), ("gamma", "C")]
            # Act: apply the filter function to the items
            return [item for item in items if filter_func(item[0], item[1])]

        monkeypatch.setattr(decker.config, "find", fake_find)

        # Act
        # Pass a keyword that should match keys containing the letter 'a'
        command_config.list_config(keywords=["al"])

        # Assert
        captured = capsys.readouterr().out
        # Assert: Check for the header and expected configuration items.
        assert_that(captured).contains("Application Configuration:")
        assert_that(captured).contains("alpha: A")
        assert_that(captured).does_not_contain("gamma: C")
        assert_that(captured).does_not_contain("beta: B")

    def test_list_config_with_items_no_keywords(self, monkeypatch, capsys):
        # Arrange
        def fake_find(filter_func):
            # Arrange: list of configuration items (key, value)
            items = [("delta", "D"), ("epsilon", "E")]
            # Act: apply the filter function to the items
            return [item for item in items if filter_func(item[0], item[1])]

        monkeypatch.setattr(decker.config, "find", fake_find)

        # Act
        command_config.list_config()

        # Assert
        captured = capsys.readouterr().out
        # Assert: Check for header and both configuration items.
        assert_that(captured).contains("Application Configuration:")
        assert_that(captured).contains("delta: D")
        assert_that(captured).contains("epsilon: E")


class TestGetConfig:
    def test_get_config_key_exists(self, monkeypatch, capsys):
        # Arrange
        def fake_has(key):
            return True

        def fake_get(key):
            return "test_value"

        def fake_decode_value(value):
            return value

        monkeypatch.setattr(decker.config, "has", fake_has)
        monkeypatch.setattr(decker.config, "get", fake_get)
        monkeypatch.setattr(decker.config, "decode_value", fake_decode_value)

        # Act
        command_config.get_config("test_key")

        # Assert
        captured = capsys.readouterr().out
        assert_that(captured).contains("test_key: test_value")

    def test_get_config_key_not_exists(self, monkeypatch, caplog):
        # Arrange
        def fake_has(key):
            return False

        def fake_error(message):
            return message

        monkeypatch.setattr(decker.config, "has", fake_has)
        monkeypatch.setattr(decker.theme, "error", fake_error)

        # Act
        command_config.get_config("nonexistent_key")

        # Assert
        assert_that(caplog.text).contains("Error: Configuration 'nonexistent_key' does not exist.")


class TestRemoveConfig:
    def test_remove_config_key_exists(self, monkeypatch, capsys):
        # Arrange
        unset_called = False
        unset_key = None

        def fake_has(key):
            return True

        def fake_unset(key):
            nonlocal unset_called, unset_key
            unset_called = True
            unset_key = key

        monkeypatch.setattr(decker.config, "has", fake_has)
        monkeypatch.setattr(decker.config, "unset", fake_unset)

        # Act
        command_config.remove_config("test_key")

        # Assert
        assert_that(unset_called).is_true()
        assert_that(unset_key).is_equal_to("test_key")
        captured = capsys.readouterr().out
        assert_that(captured).is_empty()

    def test_remove_config_key_not_exists(self, monkeypatch, caplog):
        # Arrange
        def fake_has(key):
            return False

        def fake_warning(message):
            return message

        monkeypatch.setattr(decker.config, "has", fake_has)
        monkeypatch.setattr(decker.theme, "warning", fake_warning)

        # Act
        command_config.remove_config("nonexistent_key")

        # Assert
        assert_that(caplog.text).contains("Warning: Configuration 'nonexistent_key' does not exist.")


class TestSetConfig:
    def test_set_config_new_key(self, monkeypatch):
        # Arrange
        set_called = False
        set_key = None
        set_value = None

        def fake_has(key):
            return False

        def fake_set(key, value):
            nonlocal set_called, set_key, set_value
            set_called = True
            set_key = key
            set_value = value

        monkeypatch.setattr(decker.config, "has", fake_has)
        monkeypatch.setattr(decker.config, "set", fake_set)

        # Act
        command_config.set_config("new_key", "new_value")

        # Assert
        assert_that(set_called).is_true()
        assert_that(set_key).is_equal_to("new_key")
        assert_that(set_value).is_equal_to("new_value")

    def test_set_config_existing_key(self, monkeypatch, capsys):
        # Arrange
        set_called = False
        set_key = None
        set_value = None

        def fake_has(key):
            return True

        def fake_get(key):
            return "old_value"

        def fake_decode_value(value):
            return str(value)

        def fake_set(key, value):
            nonlocal set_called, set_key, set_value
            set_called = True
            set_key = key
            set_value = value

        monkeypatch.setattr(decker.config, "has", fake_has)
        monkeypatch.setattr(decker.config, "get", fake_get)
        monkeypatch.setattr(decker.config, "decode_value", fake_decode_value)
        monkeypatch.setattr(decker.config, "set", fake_set)

        # Act
        command_config.set_config("existing_key", "updated_value")

        # Assert
        assert_that(set_called).is_true()
        assert_that(set_key).is_equal_to("existing_key")
        assert_that(set_value).is_equal_to("updated_value")
