"""Tests for configuration backends."""

from pathlib import Path

import yaml
from assertpy import assert_that

from decker.common.config.backend import DefaultBackend, MemoryBackend, UserBackend

# ---------------------------------------------------------------------------
# DefaultBackend
# ---------------------------------------------------------------------------


class TestDefaultBackend:
    def test_load_returns_nested_dict(self, tmp_path: Path):
        cfg = tmp_path / "defaults.yml"
        cfg.write_text("server:\n  port: 18861\n", encoding="utf-8")

        result = DefaultBackend(cfg).load()

        assert_that(result).is_equal_to({"server": {"port": 18861}})

    def test_load_empty_file_returns_empty_dict(self, tmp_path: Path):
        cfg = tmp_path / "empty.yml"
        cfg.write_text("", encoding="utf-8")

        result = DefaultBackend(cfg).load()

        assert_that(result).is_equal_to({})

    def test_load_missing_file_raises(self, tmp_path: Path):
        backend = DefaultBackend(tmp_path / "nonexistent.yml")

        assert_that(backend.load).raises(FileNotFoundError).when_called_with()


# ---------------------------------------------------------------------------
# UserBackend — load
# ---------------------------------------------------------------------------


class TestUserBackendLoad:
    def test_load_returns_nested_dict(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("server:\n  port: 9000\n", encoding="utf-8")

        result = UserBackend(cfg).load()

        assert_that(result).is_equal_to({"server": {"port": 9000}})

    def test_load_missing_file_returns_empty_dict(self, tmp_path: Path):
        result = UserBackend(tmp_path / "config.yaml").load()

        assert_that(result).is_equal_to({})


# ---------------------------------------------------------------------------
# UserBackend — save
# ---------------------------------------------------------------------------


class TestUserBackendSave:
    def test_save_creates_file_and_parent_dirs(self, tmp_path: Path):
        cfg = tmp_path / "nested" / "dir" / "config.yaml"
        backend = UserBackend(cfg)

        backend.save({"server": {"port": 1234}})

        assert_that(cfg.exists()).is_true()
        with open(cfg, encoding="utf-8") as fh:
            assert_that(yaml.safe_load(fh)).is_equal_to({"server": {"port": 1234}})

    def test_save_overwrites_existing_file(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        backend = UserBackend(cfg)
        backend.save({"a": 1})

        backend.save({"b": 2})

        with open(cfg, encoding="utf-8") as fh:
            assert_that(yaml.safe_load(fh)).is_equal_to({"b": 2})

    def test_roundtrip(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        data = {"server": {"port": 18861, "host": "localhost"}}
        backend = UserBackend(cfg)

        backend.save(data)
        result = backend.load()

        assert_that(result).is_equal_to(data)


# ---------------------------------------------------------------------------
# MemoryBackend
# ---------------------------------------------------------------------------


class TestMemoryBackend:
    def test_load_initially_empty(self):
        assert_that(MemoryBackend().load()).is_equal_to({})

    def test_save_and_load_roundtrip(self):
        backend = MemoryBackend()
        data = {"server": {"port": 42}}

        backend.save(data)

        assert_that(backend.load()).is_equal_to(data)

    def test_save_replaces_previous_data(self):
        backend = MemoryBackend()
        backend.save({"a": 1})

        backend.save({"b": 2})

        assert_that(backend.load()).is_equal_to({"b": 2})

    def test_save_does_not_write_to_disk(self, tmp_path: Path):
        backend = MemoryBackend()
        backend.save({"x": 99})
        assert_that(list(tmp_path.iterdir())).is_empty()
