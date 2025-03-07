import os
import tempfile

import toml
from assertpy import assert_that

from decker_server.config.backend import BackendManager, TomlFileBackend


class TestTomlBackendLoad:
    def test_load_file_not_found(self):
        # Arrange
        temp_path = "non_existent_config.toml"
        backend = TomlFileBackend(temp_path)

        # Act & Assert
        try:
            backend.load()
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError as e:
            assert_that(str(e)).contains(temp_path)

    def test_load_not_readable(self):
        # Arrange
        with tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="UTF-8") as tmp_file:
            tmp_file.write("server = { port = 8080 }")
            temp_path = tmp_file.name
        # Remove read permission
        os.chmod(temp_path, 0o000)
        backend = TomlFileBackend(temp_path)

        # Act & Assert
        try:
            backend.load()
            assert False, "Expected PermissionError"
        except PermissionError as e:
            assert_that(str(e)).contains(temp_path)
        finally:
            os.chmod(temp_path, 0o644)
            os.remove(temp_path)

    def test_load_without_server_key(self):
        # Arrange
        with tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="UTF-8") as tmp_file:
            toml.dump({"not_server": {"key": "value"}}, tmp_file)
            temp_path = tmp_file.name
        backend = TomlFileBackend(temp_path)

        # Act
        settings = backend.load()

        # Assert
        assert_that(settings).is_empty()
        os.remove(temp_path)

    def test_load_with_server_key(self):
        # Arrange
        sample_config = {"server": {"port": 8080, "host": "localhost", "debug": True}}
        with tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="UTF-8") as tmp_file:
            toml.dump(sample_config, tmp_file)
            temp_path = tmp_file.name
        backend = TomlFileBackend(temp_path)

        # Act
        settings = backend.load()

        # Assert
        expected_keys = {"port", "host", "debug"}
        for k in expected_keys:
            assert_that(settings).contains_key(k)
        assert_that(settings["port"]).is_equal_to(8080)
        assert_that(settings["host"]).is_equal_to("localhost")
        assert_that(settings["debug"]).is_equal_to(True)
        os.remove(temp_path)


class TestTomlBackendSave:
    def test_save_not_readable(self):
        # Arrange
        with tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="UTF-8") as tmp_file:
            tmp_file.write("server = { port = 8080 }")
            temp_path = tmp_file.name
        os.chmod(temp_path, 0o000)
        backend = TomlFileBackend(temp_path)
        settings = {"new": {"key": "value"}}

        # Act & Assert
        try:
            backend.save(settings)
            assert False, "Expected PermissionError"
        except PermissionError as e:
            assert_that(str(e)).contains(temp_path)
        finally:
            os.chmod(temp_path, 0o644)
            os.remove(temp_path)

    def test_save_success(self, monkeypatch):
        # Arrange
        # Create a temporary config file with initial content
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="UTF-8") as tmp_file:
            toml.dump({"server": {"initial": "data"}}, tmp_file)
            temp_path = tmp_file.name
        backend = TomlFileBackend(temp_path)
        new_settings = {"app": {"mode": "production", "debug": False}}

        # Act
        backend.save(new_settings)

        # Assert
        with open(temp_path, "r", encoding="UTF-8") as f:
            data = toml.load(f)

        # Verify only 'server' key exists with new settings unflattened
        assert_that("server" in data).is_true()

        server_config = data["server"]
        assert_that(server_config).is_equal_to({"app": {"mode": "production", "debug": False}})

        os.remove(temp_path)


class DummyBackend:
    # see DummyBackend
    def __init__(self):
        """Initializes the dummy backend.

        Returns:
            None.
        """
        self.load_called = 0
        self.save_called = 0
        self.saved_settings = None

    def load(self):
        """Simulates a synchronous load operation.

        Returns:
            list[Setting]: A list containing a dummy Setting.
        """
        self.load_called += 1

        return {"dummy": {"key": "dummy.value"}}

    def save(self, settings):
        """Simulates a synchronous save operation.

        Args:
            settings (list[Setting]): Settings to save.

        Returns:
            None.
        """
        self.save_called += 1
        self.saved_settings = settings


class TestBackendManagerLoad:
    # see TestConfigFileManagerLoad
    def test_load_calls_backend_load_and_returns_settings(self):
        """Tests that manager.load calls backend.load and returns correct settings."""
        # Arrange
        dummy_backend = DummyBackend()
        manager = BackendManager(dummy_backend)

        # Act
        settings = manager.load()

        # Assert
        assert_that(settings).is_equal_to({"dummy": {"key": "dummy.value"}})


class TestBackendManagerSave:
    # see TestConfigFileManagerSave
    def test_save_calls_backend_save_and_saves_settings(self):
        """Tests that manager.save calls backend.save and the settings are saved properly."""
        # Arrange
        dummy_backend = DummyBackend()
        manager = BackendManager(dummy_backend)
        new_settings = {"new": {"key": "value"}}

        # Act
        manager.save(new_settings)
        manager.flush()

        # Assert
        assert_that(dummy_backend.save_called).is_equal_to(1)
        assert_that(dummy_backend.saved_settings).is_equal_to(new_settings)
