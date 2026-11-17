import json
from pathlib import Path
from typing import Iterator

import pytest
from assertpy import assert_that

from decker.common import config
from decker.server.repositories import (
    FetchError,
    RepositoryError,
    RepositoryStore,
    fetch,
)
from tests.server.http_fixture import FixtureServer


def _index(name: str, plugin_ids: list[str], icon: str | None = None) -> bytes:
    plugins = []
    for pid in plugin_ids:
        plugin: dict = {
            "id": pid,
            "name": pid,
            "versions": [
                {
                    "version": "1.0.0",
                    "url": f"{pid}.deckerplugin",
                    "size": 10,
                    "sha256": "0" * 64,
                    "released": "2026-01-01",
                    "contributes": {"actions": ["a"]},
                }
            ],
        }
        if icon:
            plugin["icon"] = icon
        plugins.append(plugin)
    return json.dumps({"format": 1, "name": name, "generated": "2026-01-01T00:00:00Z", "plugins": plugins}).encode()


@pytest.fixture(autouse=True)
def _tmp_config(tmp_path: Path) -> Iterator[None]:
    config.configure_prefix(tmp_path / "config" / "config.yaml")
    yield
    config.configure_prefix(tmp_path / "config" / "config.yaml")


@pytest.fixture
def web(tmp_path: Path) -> Iterator[FixtureServer]:
    root = tmp_path / "web"
    root.mkdir()
    server = FixtureServer(root).start()
    yield server
    try:
        server.stop()
    except OSError:
        pass


def _root(web: FixtureServer) -> Path:
    return Path(web.RequestHandlerClass.keywords["directory"])  # type: ignore[attr-defined]


def _publish(web: FixtureServer, filename: str, data: bytes) -> str:
    (_root(web) / filename).write_bytes(data)
    return f"{web.base_url}/{filename}"


@pytest.fixture
def store(tmp_path: Path) -> RepositoryStore:
    return RepositoryStore(tmp_path / "cache")


def test_add_valid_repository_persists_url(store: RepositoryStore, web: FixtureServer) -> None:
    url = _publish(web, "a.json", _index("A", ["com.t.p1", "com.t.p2"]))
    info = store.add(url)
    assert_that(info.name).is_equal_to("A")
    assert_that(info.plugin_count).is_equal_to(2)
    assert_that(info.error).is_none()
    assert_that(store.urls()).is_equal_to([url])
    assert_that(config.get("plugin.repositories")).is_equal_to([url])
    assert_that([i.url for i in store.list_repositories()]).is_equal_to([url])


def test_add_invalid_repository_not_saved(store: RepositoryStore, web: FixtureServer) -> None:
    missing = f"{web.base_url}/missing.json"
    with pytest.raises(RepositoryError):
        store.add(missing)
    bad = _publish(web, "bad.json", b"not json")
    with pytest.raises(RepositoryError):
        store.add(bad)
    assert_that(store.urls()).is_empty()


def test_add_duplicate_rejected(store: RepositoryStore, web: FixtureServer) -> None:
    url = _publish(web, "a.json", _index("A", ["com.t.p1"]))
    store.add(url)
    with pytest.raises(RepositoryError):
        store.add(url)
    assert_that(store.urls()).is_length(1)


def test_remove_clears_cache(store: RepositoryStore, web: FixtureServer) -> None:
    url = _publish(web, "a.json", _index("A", ["com.t.p1"]))
    store.add(url)
    assert_that(store.remove(url)).is_true()
    assert_that(store.urls()).is_empty()
    assert_that(store.catalog()).is_empty()
    assert_that(list((store._cache_dir).glob("*/index.json"))).is_empty()  # pylint: disable=protected-access
    assert_that(store.remove(url)).is_false()


def test_refresh_failure_keeps_cached_catalog(store: RepositoryStore, web: FixtureServer) -> None:
    url = _publish(web, "a.json", _index("A", ["com.t.p1"]))
    store.add(url)
    before = store.catalog()
    web.stop()
    infos = store.refresh_all()
    assert_that(store.catalog()).is_equal_to(before)
    assert_that(infos[0].error).is_not_none()
    assert_that(infos[0].plugin_count).is_equal_to(1)


def test_refresh_success_updates_catalog(store: RepositoryStore, web: FixtureServer) -> None:
    url = _publish(web, "a.json", _index("A", ["com.t.p1"]))
    store.add(url)
    _publish(web, "a.json", _index("A", ["com.t.p1", "com.t.p2"]))
    infos = store.refresh_all()
    assert_that(infos[0].plugin_count).is_equal_to(2)
    assert_that(infos[0].error).is_none()


def test_timeout(web: FixtureServer) -> None:
    url = _publish(web, "a.json", _index("A", ["com.t.p1"]))
    web.delay = 2.0
    with pytest.raises(FetchError):
        fetch(url, 1000, timeout=0.5)


def test_oversize_body_rejected(web: FixtureServer) -> None:
    url = _publish(web, "big.bin", b"x" * 2000)
    with pytest.raises(FetchError):
        fetch(url, 1000)
    assert_that(fetch(url, 2000)).is_length(2000)


def test_http_error_raises(web: FixtureServer) -> None:
    web.status = 500
    with pytest.raises(FetchError):
        fetch(f"{web.base_url}/x", 100)


def test_file_scheme(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_bytes(b"hi")
    assert_that(fetch(path.as_uri(), 100)).is_equal_to(b"hi")


def test_rejects_unsupported_scheme() -> None:
    with pytest.raises(FetchError):
        fetch("ftp://example.com/index.json", 100)


def test_first_repository_wins(store: RepositoryStore, web: FixtureServer) -> None:
    first = _publish(web, "a.json", _index("A", ["com.t.shared", "com.t.onlya"]))
    second = _publish(web, "b.json", _index("B", ["com.t.shared"]))
    store.add(first)
    store.add(second)
    entries = {(e.repository_url, e.plugin.id): e for e in store.catalog()}
    assert_that(entries[(first, "com.t.shared")].shadowed_by).is_none()
    assert_that(entries[(second, "com.t.shared")].shadowed_by).is_equal_to(first)
    found = store.find("com.t.shared")
    assert found is not None
    assert_that(found.repository_url).is_equal_to(first)
    assert_that(store.find("com.t.nope")).is_none()


def test_icon_cached_after_first_fetch(store: RepositoryStore, web: FixtureServer) -> None:
    (_root(web) / "p1.png").write_bytes(b"PNGDATA")
    url = _publish(web, "a.json", _index("A", ["com.t.p1"], icon="p1.png"))
    store.add(url)
    assert_that(store.icon("com.t.p1")).is_equal_to(b"PNGDATA")
    web.stop()
    assert_that(store.icon("com.t.p1")).is_equal_to(b"PNGDATA")
    assert_that(store.icon("com.t.unknown")).is_none()


def test_icon_missing_or_failing_returns_none(store: RepositoryStore, web: FixtureServer) -> None:
    url = _publish(web, "a.json", _index("A", ["com.t.p1"], icon="gone.png"))
    store.add(url)
    assert_that(store.icon("com.t.p1")).is_none()


def test_state_persists_last_check(tmp_path: Path, store: RepositoryStore) -> None:
    assert_that(store.last_check()).is_none()
    store.mark_checked(1234.5)
    assert_that(RepositoryStore(tmp_path / "cache").last_check()).is_equal_to(1234.5)
