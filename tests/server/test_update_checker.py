import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, cast
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that

from decker.common import config, paths
from decker.plugin.target import ActionTarget
from decker.server.key_assignments import KeyAssignmentStore
from decker.server.plugins import PluginManager
from decker.server.repositories import FetchError, RepositoryStore
from decker.server.update_checker import UpdateChecker

DAY = 86400.0


def _version(version: str, decker: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "version": version,
        "url": "p.deckerplugin",
        "size": 10,
        "sha256": "0" * 64,
        "released": "2026-01-01",
        "contributes": {"actions": ["a"]},
    }
    if decker:
        item["decker"] = decker
    return item


def _write_index(path: Path, plugins: dict[str, list[dict[str, Any]]]) -> str:
    body = {
        "format": 1,
        "name": "R",
        "generated": "2026-01-01T00:00:00Z",
        "plugins": [{"id": pid, "name": pid, "versions": versions} for pid, versions in plugins.items()],
    }
    path.write_text(json.dumps(body))
    return path.as_uri()


class FakePlugins:
    def __init__(self, installed: dict[str, str]) -> None:
        self.installed = installed

    def plugins(self) -> list[Any]:
        return [
            SimpleNamespace(manifest=SimpleNamespace(id=pid, version=ver, name=f"Name {pid}"))
            for pid, ver in self.installed.items()
        ]


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _tmp_config(tmp_path: Path) -> Iterator[None]:
    config.configure_prefix(tmp_path / "config" / "config.yaml")
    config.set("plugin.repositories", [])
    yield
    config.configure_prefix(paths.config_yaml())


@pytest.fixture
def keys() -> Iterator[KeyAssignmentStore]:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = KeyAssignmentStore(db_path=Path(tmpdir) / "k.db")
        store.create(MagicMock())
        yield store
        store.destroy()


class Env:
    def __init__(self, tmp_path: Path, keys: KeyAssignmentStore) -> None:
        self.tmp_path = tmp_path
        self.keys = keys
        self.store = RepositoryStore(tmp_path / "cache")
        self.plugins = FakePlugins({})
        self.clock = Clock()
        self.pushed: list[tuple[str, dict[str, Any]]] = []
        self.checker = UpdateChecker(
            self.store,
            cast(PluginManager, self.plugins),
            keys,
            lambda name, payload: self.pushed.append((name, payload)),
            self.clock,
        )

    def publish(self, plugins: dict[str, list[dict[str, Any]]]) -> None:
        url = _write_index(self.tmp_path / "index.json", plugins)
        config.set("plugin.repositories", [url])
        self.store.refresh_all()


@pytest.fixture
def env(tmp_path: Path, keys: KeyAssignmentStore) -> Env:
    return Env(tmp_path, keys)


def test_update_detected(env: Env) -> None:
    env.publish({"com.t.a": [_version("2.0.0"), _version("1.0.0")]})
    env.plugins.installed = {"com.t.a": "1.0.0"}
    report = env.checker.check_now()
    assert_that(report.to_payload()["updates"]).is_equal_to(
        [{"id": "com.t.a", "name": "Name com.t.a", "installed": "1.0.0", "available": "2.0.0"}]
    )


def test_newer_local_version_is_up_to_date(env: Env) -> None:
    env.publish({"com.t.a": [_version("1.0.0")]})
    env.plugins.installed = {"com.t.a": "1.5.0"}
    assert_that(env.checker.check_now().updates).is_empty()


def test_incompatible_version_ignored(env: Env) -> None:
    env.publish({"com.t.a": [_version("3.0.0", ">=999"), _version("1.0.0")]})
    env.plugins.installed = {"com.t.a": "1.0.0"}
    assert_that(env.checker.check_now().updates).is_empty()


def test_missing_plugin_reported_with_key_count(env: Env) -> None:
    env.publish({"com.t.m": [_version("1.2.0")]})
    for index in range(2):
        target = ActionTarget(
            plugin_uuid="com.t.m", action_uuid="a", context_id=f"c{index}", device_id="d", key_index=index
        )
        env.keys.assign("d", "p", index, target, {})
    report = env.checker.check_now()
    assert_that(report.to_payload()["missing"]).is_equal_to(
        [{"id": "com.t.m", "name": "com.t.m", "version": "1.2.0", "keys": 2}]
    )


def test_weekly_not_due_after_restart(env: Env) -> None:
    env.store.mark_checked(env.clock.now - 2 * DAY)
    assert_that(env.checker.schedule()).is_equal_to("weekly")
    assert_that(env.checker.check_if_due()).is_false()


def test_due_after_interval(env: Env) -> None:
    env.store.mark_checked(env.clock.now - 8 * DAY)
    assert_that(env.checker.check_if_due()).is_true()
    assert_that(env.store.last_check()).is_equal_to(env.clock.now)
    assert_that(env.checker.check_if_due()).is_false()


def test_due_when_never_checked(env: Env) -> None:
    assert_that(env.checker.check_if_due()).is_true()


def test_manual_never_due(env: Env) -> None:
    env.checker.set_schedule("manual")
    env.store.mark_checked(env.clock.now - 400 * DAY)
    assert_that(env.checker.check_if_due()).is_false()


def test_start_uses_cache_without_network(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    env.publish({"com.t.a": [_version("2.0.0")]})
    env.plugins.installed = {"com.t.a": "1.0.0"}
    env.store.mark_checked(env.clock.now)

    def boom(*_args: Any, **_kwargs: Any) -> bytes:
        raise FetchError("offline")

    monkeypatch.setattr("decker.server.repositories.fetch", boom)
    env.checker.start()
    try:
        assert_that(env.checker.report().updates).is_length(1)
        assert_that(env.pushed).is_length(1)
        assert_that(env.pushed[0][0]).is_equal_to("plugin_updates_available")
    finally:
        env.checker.stop()


def test_push_only_on_change(env: Env) -> None:
    env.publish({"com.t.a": [_version("2.0.0")]})
    env.plugins.installed = {"com.t.a": "1.0.0"}
    env.checker.check_now()
    env.checker.check_now()
    assert_that(env.pushed).is_length(1)
    env.plugins.installed = {"com.t.a": "2.0.0"}
    env.checker.check_now()
    assert_that(env.pushed).is_length(2)
    assert_that(env.pushed[1][1]).is_equal_to({"updates": [], "missing": []})


def test_set_schedule_rejects_unknown(env: Env) -> None:
    with pytest.raises(ValueError):
        env.checker.set_schedule("hourly")
    env.checker.set_schedule("daily")
    assert_that(env.checker.schedule()).is_equal_to("daily")


def test_failed_check_does_not_mark_checked(env: Env) -> None:
    config.set("plugin.repositories", [(env.tmp_path / "missing.json").as_uri()])
    env.checker.check_now()
    assert_that(env.store.last_check()).is_none()
    assert_that(env.checker.check_if_due()).is_true()


def test_future_last_check_is_due(env: Env) -> None:
    env.store.mark_checked(env.clock.now + 10 * DAY)
    assert_that(env.checker.check_if_due()).is_true()
