"""Tests for decker.server.settings."""

import pytest
from assertpy import assert_that

from decker.server.settings import (
    ServerSettings,
    SettingsError,
    read_settings,
    validate,
    write_settings,
)

_MIB = 1024 * 1024


def test_read_defaults(isolated_config) -> None:
    settings = read_settings()

    assert_that(settings).is_equal_to(ServerSettings(18861, 1024 * _MIB, 4 * _MIB, False))


@pytest.mark.parametrize(
    "values",
    [
        {"port": 0},
        {"port": 65536},
        {"port": True},
        {"port": "80"},
        {"memory_limit": 1},
        {"memory_limit": 10**13},
        {"memory_limit": -5},
        {"icon_max_file_size": 1},
        {"icon_max_file_size": 10**12},
        {"stop_when_last_client_leaves": "yes"},
        {"host": "0.0.0.0"},
        {"nonsense": 1},
    ],
)
def test_validate_rejects(isolated_config, values: dict[str, object]) -> None:
    with pytest.raises(SettingsError):
        validate(values)


def test_validate_merges_partial_values(isolated_config) -> None:
    result = validate({"port": 19000})

    assert_that(result.port).is_equal_to(19000)
    assert_that(result.memory_limit).is_equal_to(1024 * _MIB)


def test_write_reports_restart_only_for_restart_keys(isolated_config) -> None:
    assert_that(write_settings(validate({"stop_when_last_client_leaves": True}))).is_false()
    assert_that(isolated_config.get_as("server.stop_when_last_client_leaves", bool)).is_true()

    assert_that(write_settings(validate({"port": 19000}))).is_true()
    assert_that(isolated_config.get_as("server.port", int)).is_equal_to(19000)


def test_write_same_values_needs_no_restart(isolated_config) -> None:
    assert_that(write_settings(read_settings())).is_false()


def test_write_persists_memory_and_image_limits(isolated_config) -> None:
    assert_that(write_settings(validate({"memory_limit": 256 * _MIB, "icon_max_file_size": 2 * _MIB}))).is_true()

    assert_that(isolated_config.get_as("server.memory_limit", int)).is_equal_to(256 * _MIB)
    assert_that(isolated_config.get_as("icons.max_file_size", int)).is_equal_to(2 * _MIB)
