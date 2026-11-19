from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common.model import ScreensaverSettings
from decker.server.screensaver.screensaver_store import ScreensaverStore


@pytest.fixture()
def store(tmp_path):
    s = ScreensaverStore(db_path=tmp_path / "test.db")
    s.create(MagicMock())
    yield s
    s.destroy()


def test_store_returns_defaults_then_roundtrips(store):
    assert_that(store.get("dev1")).is_equal_to(ScreensaverSettings())
    changed = replace(ScreensaverSettings(), brightness=30, content="image", image_path="/a.png")

    store.set("dev1", changed)

    assert_that(store.get("dev1")).is_equal_to(changed)
    assert_that(store.get("dev2")).is_equal_to(ScreensaverSettings())


def test_store_rejects_invalid(store):
    with pytest.raises(ValueError, match="brightness"):
        store.set("dev1", replace(ScreensaverSettings(), brightness=0))


def test_store_survives_reopen(tmp_path):
    path = tmp_path / "test.db"
    first = ScreensaverStore(db_path=path)
    first.create(MagicMock())
    first.set("dev1", ScreensaverSettings(timeout_minutes=15))
    first.destroy()

    second = ScreensaverStore(db_path=path)
    second.create(MagicMock())
    try:
        assert_that(second.get("dev1").timeout_minutes).is_equal_to(15)
    finally:
        second.destroy()
