"""Tests for the Config class and module-level API."""

from pathlib import Path
from typing import Any

import pytest
from assertpy import assert_that

from decker.common.config import Config, ValueType, _convert, _to_bool, _to_list
from decker.common.config.backend import DefaultBackend, MemoryBackend, UserBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_config(
    defaults: dict[str, Any] | None = None,
    user: dict[str, Any] | None = None,
    tmp_path: Path | None = None,
) -> Config:
    """Build a Config backed by temp YAML files and an in-memory backend."""
    import yaml

    assert tmp_path is not None
    defaults_file = tmp_path / "defaults.yml"
    defaults_file.write_text(yaml.dump(defaults or {}), encoding="utf-8")

    user_file = tmp_path / "config.yaml"
    if user:
        user_file.write_text(yaml.dump(user), encoding="utf-8")

    cfg = Config(DefaultBackend(defaults_file), UserBackend(user_file), MemoryBackend())
    cfg.load()
    return cfg


# ---------------------------------------------------------------------------
# has
# ---------------------------------------------------------------------------


class TestHas:
    def test_key_in_defaults(self, tmp_path: Path):
        cfg = make_config({"server": {"port": 18861}}, tmp_path=tmp_path)
        assert_that(cfg.has("server.port")).is_true()

    def test_key_in_user(self, tmp_path: Path):
        cfg = make_config(user={"server": {"port": 9000}}, tmp_path=tmp_path)
        assert_that(cfg.has("server.port")).is_true()

    def test_key_in_memory(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        cfg.load_memory({"server": {"port": 1234}})
        assert_that(cfg.has("server.port")).is_true()

    def test_missing_key_returns_false(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        assert_that(cfg.has("nonexistent.key")).is_false()


# ---------------------------------------------------------------------------
# get — precedence
# ---------------------------------------------------------------------------


class TestGet:
    def test_returns_default_value(self, tmp_path: Path):
        cfg = make_config({"server": {"port": 18861}}, tmp_path=tmp_path)
        assert_that(cfg.get("server.port")).is_equal_to(18861)

    def test_user_overrides_default(self, tmp_path: Path):
        cfg = make_config(
            {"server": {"port": 18861}},
            user={"server": {"port": 9000}},
            tmp_path=tmp_path,
        )
        assert_that(cfg.get("server.port")).is_equal_to(9000)

    def test_memory_overrides_user_and_default(self, tmp_path: Path):
        cfg = make_config(
            {"server": {"port": 18861}},
            user={"server": {"port": 9000}},
            tmp_path=tmp_path,
        )
        cfg.load_memory({"server": {"port": 1234}})
        assert_that(cfg.get("server.port")).is_equal_to(1234)

    def test_missing_key_raises_key_error(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        assert_that(cfg.get).raises(KeyError).when_called_with("no.such.key")


# ---------------------------------------------------------------------------
# get_or_default
# ---------------------------------------------------------------------------


class TestGetOrDefault:
    def test_returns_value_when_key_exists(self, tmp_path: Path):
        cfg = make_config({"x": 42}, tmp_path=tmp_path)
        assert_that(cfg.get_or_default("x", 0)).is_equal_to(42)

    def test_returns_default_when_key_missing(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        assert_that(cfg.get_or_default("missing", 99)).is_equal_to(99)


# ---------------------------------------------------------------------------
# get_as
# ---------------------------------------------------------------------------


class TestGetAs:
    def test_int_returned_as_str(self, tmp_path: Path):
        cfg = make_config({"port": 8080}, tmp_path=tmp_path)
        assert_that(cfg.get_as("port", str)).is_equal_to("8080")

    def test_str_converted_to_int(self, tmp_path: Path):
        cfg = make_config({"port": "8080"}, tmp_path=tmp_path)
        assert_that(cfg.get_as("port", int)).is_equal_to(8080)

    def test_str_converted_to_bool(self, tmp_path: Path):
        cfg = make_config({"flag": "true"}, tmp_path=tmp_path)
        assert_that(cfg.get_as("flag", bool)).is_true()

    def test_comma_string_to_list(self, tmp_path: Path):
        cfg = make_config({"tags": "a,b,c"}, tmp_path=tmp_path)
        assert_that(cfg.get_as("tags", list)).is_equal_to(["a", "b", "c"])

    def test_missing_key_raises_key_error(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        assert_that(cfg.get_as).raises(KeyError).when_called_with("missing", int)

    def test_invalid_conversion_raises_type_error(self, tmp_path: Path):
        cfg = make_config({"val": "not-a-number"}, tmp_path=tmp_path)
        assert_that(cfg.get_as).raises(TypeError).when_called_with("val", int)


# ---------------------------------------------------------------------------
# get_as_or_default
# ---------------------------------------------------------------------------


class TestGetAsOrDefault:
    def test_returns_converted_value(self, tmp_path: Path):
        cfg = make_config({"n": "42"}, tmp_path=tmp_path)
        assert_that(cfg.get_as_or_default("n", int, 0)).is_equal_to(42)

    def test_returns_default_on_missing_key(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        assert_that(cfg.get_as_or_default("missing", int, 7)).is_equal_to(7)

    def test_returns_default_on_conversion_failure(self, tmp_path: Path):
        cfg = make_config({"v": "bad"}, tmp_path=tmp_path)
        assert_that(cfg.get_as_or_default("v", int, -1)).is_equal_to(-1)


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_returns_all_merged(self, tmp_path: Path):
        cfg = make_config(
            {"server": {"port": 18861}},
            user={"client": {"host": "localhost"}},
            tmp_path=tmp_path,
        )
        result = cfg.get_all()
        assert_that(result).contains_key("server.port")
        assert_that(result).contains_key("client.host")

    def test_user_value_shadows_default_in_merged(self, tmp_path: Path):
        cfg = make_config(
            {"server": {"port": 18861}},
            user={"server": {"port": 9000}},
            tmp_path=tmp_path,
        )
        assert_that(cfg.get_all()["server.port"]).is_equal_to(9000)

    def test_filtered_by_prefix(self, tmp_path: Path):
        cfg = make_config(
            {"server": {"port": 18861, "host": "localhost"}, "client": {"port": 9000}},
            tmp_path=tmp_path,
        )
        result = cfg.get_all("server")
        assert_that(result).contains_key("server.port")
        assert_that(result).contains_key("server.host")
        assert_that(result).does_not_contain_key("client.port")

    def test_exact_key_included_in_prefix_filter(self, tmp_path: Path):
        cfg = make_config({"x": 1, "x.y": 2}, tmp_path=tmp_path)
        result = cfg.get_all("x")
        assert_that(result).contains_key("x")
        assert_that(result).contains_key("x.y")


# ---------------------------------------------------------------------------
# set / unset
# ---------------------------------------------------------------------------


class TestSet:
    def test_set_persists_to_user_layer(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        cfg.set("server.port", 9999)
        assert_that(cfg.get("server.port")).is_equal_to(9999)

    def test_set_persists_to_disk(self, tmp_path: Path):
        import yaml

        user_file = tmp_path / "config.yaml"
        defaults_file = tmp_path / "defaults.yml"
        defaults_file.write_text("", encoding="utf-8")

        cfg = Config(DefaultBackend(defaults_file), UserBackend(user_file), MemoryBackend())
        cfg.load()
        cfg.set("server.port", 4242)

        with open(user_file, encoding="utf-8") as fh:
            saved = yaml.safe_load(fh)
        assert_that(saved["server"]["port"]).is_equal_to(4242)

    def test_set_invalid_type_raises_type_error(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        assert_that(cfg.set).raises(TypeError).when_called_with("key", {"nested": "dict"})

    def test_set_does_not_override_memory(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        cfg.load_memory({"server": {"port": 1111}})
        cfg.set("server.port", 2222)
        # memory still wins
        assert_that(cfg.get("server.port")).is_equal_to(1111)


class TestUnset:
    def test_unset_removes_key_from_user(self, tmp_path: Path):
        cfg = make_config(user={"server": {"port": 9000}}, tmp_path=tmp_path)
        cfg.unset("server.port")
        # falls back to default (none here), so KeyError
        assert_that(cfg.has("server.port")).is_false()

    def test_unset_removes_sub_keys(self, tmp_path: Path):
        cfg = make_config(
            user={"server": {"port": 9000, "host": "remote"}},
            tmp_path=tmp_path,
        )
        cfg.unset("server")
        assert_that(cfg.has("server.port")).is_false()
        assert_that(cfg.has("server.host")).is_false()

    def test_unset_nonexistent_is_noop(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        cfg.unset("does.not.exist")  # should not raise

    def test_unset_falls_back_to_default(self, tmp_path: Path):
        cfg = make_config(
            {"server": {"port": 18861}},
            user={"server": {"port": 9000}},
            tmp_path=tmp_path,
        )
        cfg.unset("server.port")
        assert_that(cfg.get("server.port")).is_equal_to(18861)


# ---------------------------------------------------------------------------
# load_memory
# ---------------------------------------------------------------------------


class TestLoadMemory:
    def test_memory_overrides_all(self, tmp_path: Path):
        cfg = make_config(
            {"server": {"port": 18861}},
            user={"server": {"port": 9000}},
            tmp_path=tmp_path,
        )
        cfg.load_memory({"server": {"port": 1}})
        assert_that(cfg.get("server.port")).is_equal_to(1)

    def test_memory_accepts_flat_keys(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        cfg.load_memory({"server.port": 42})
        assert_that(cfg.get("server.port")).is_equal_to(42)

    def test_memory_replaces_previous_memory(self, tmp_path: Path):
        cfg = make_config(tmp_path=tmp_path)
        cfg.load_memory({"a": 1})
        cfg.load_memory({"b": 2})
        assert_that(cfg.has("a")).is_false()
        assert_that(cfg.get("b")).is_equal_to(2)


# ---------------------------------------------------------------------------
# _convert helpers
# ---------------------------------------------------------------------------


class TestConvert:
    @pytest.mark.parametrize(
        "value,target,expected",
        [
            ("42", int, 42),
            (42, str, "42"),
            ("3.14", float, 3.14),
            ("true", bool, True),
            ("no", bool, False),
            (1, bool, True),
            (0, bool, False),
            ("a,b,c", list, ["a", "b", "c"]),
            ([1, 2], list, [1, 2]),
        ],
    )
    def test_standard_conversions(self, value: Any, target: type, expected: Any):
        assert_that(_convert(value, target)).is_equal_to(expected)

    def test_list_with_item_type(self):
        assert_that(_convert("1,2,3", list[int])).is_equal_to([1, 2, 3])

    def test_invalid_int_raises_type_error(self):
        assert_that(_convert).raises(TypeError).when_called_with("abc", int)

    def test_ambiguous_bool_raises_value_error(self):
        assert_that(_to_bool).raises(ValueError).when_called_with("maybe")


class TestToBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "1", "y", "on"])
    def test_truthy_strings(self, value: str):
        assert_that(_to_bool(value)).is_true()

    @pytest.mark.parametrize("value", ["false", "False", "no", "0", "n", "off"])
    def test_falsy_strings(self, value: str):
        assert_that(_to_bool(value)).is_false()

    def test_bool_passthrough(self):
        assert_that(_to_bool(True)).is_true()
        assert_that(_to_bool(False)).is_false()

    def test_numeric(self):
        assert_that(_to_bool(1)).is_true()
        assert_that(_to_bool(0)).is_false()


def test_the_device_watch_interval_defaults_to_two_seconds() -> None:
    from decker.common import config

    assert_that(config.get("server.device_watch_interval")).is_equal_to(2.0)
