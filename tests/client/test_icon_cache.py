"""Tests for decker.client.icon_cache."""

# pylint: disable=protected-access,unused-argument,redefined-outer-name
import hashlib
import re
import shutil
from pathlib import Path

import pytest
from assertpy import assert_that
from PyQt6.QtGui import QColor, QPixmap

import decker.client.icon_cache as module
import decker.common.paths as paths
from decker.client.icon_cache import IconThumbnailCache, icon_cache

_PACK = "com.x.solid"


def _pix(color: str = "#ff0000", size: int = 8) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color))
    return pixmap


def _packs(version: str | None = "1.0.0", pack: str = _PACK) -> list[dict]:
    entry: dict = {"id": pack, "name": "Pack"}
    if version is not None:
        entry["plugin_version"] = version
    return [entry]


def _centre(pixmap: QPixmap) -> tuple[int, int, int]:
    image = pixmap.toImage()
    colour = image.pixelColor(image.width() // 2, image.height() // 2)
    return colour.red(), colour.green(), colour.blue()


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


@pytest.fixture
def cache(tmp_path: Path, qapp) -> IconThumbnailCache:
    result = IconThumbnailCache(tmp_path / "cache")
    result.update_packs(_packs())
    return result


class TestVersions:
    def test_get_misses_when_the_version_is_unknown(self, tmp_path, qapp):
        unknown = IconThumbnailCache(tmp_path / "c")
        assert_that(unknown.get(_PACK, "a.svg", 64, "#ffffff")).is_none()
        assert_that(unknown.version_of(_PACK)).is_none()

    def test_version_of_reports_the_listed_version(self, cache):
        assert_that(cache.version_of(_PACK)).is_equal_to("1.0.0")

    def test_packs_without_plugin_version_are_not_cached_at_all(self, tmp_path, qapp):
        old = IconThumbnailCache(tmp_path / "c")
        old.update_packs(_packs(version=None))

        old.put(_PACK, "a.svg", 64, "#ffffff", _pix())

        assert_that(old.get(_PACK, "a.svg", 64, "#ffffff")).is_none()
        assert_that(list((tmp_path / "c").rglob("*"))).is_empty()

    def test_malformed_pack_entries_are_ignored(self, tmp_path, qapp):
        messy = IconThumbnailCache(tmp_path / "c")
        messy.update_packs([{"name": "no id"}, "garbage", {"id": "x", "plugin_version": ""}, None])  # type: ignore[list-item]
        assert_that(messy.version_of("x")).is_none()


class TestHitsAndMisses:
    def test_put_then_get_hits_memory_and_disk(self, cache, tmp_path):
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix("#00ff00"))

        assert_that(_centre(cache.get(_PACK, "a.svg", 64, "#ffffff"))).is_equal_to((0, 255, 0))
        fresh = IconThumbnailCache(tmp_path / "cache")  # a new process: nothing in memory
        fresh.update_packs(_packs())
        hit = fresh.get(_PACK, "a.svg", 64, "#ffffff")
        assert hit is not None
        assert_that(_centre(hit)).is_equal_to((0, 255, 0))

    def test_miss_returns_none(self, cache):
        assert_that(cache.get(_PACK, "nope.svg", 64, "#ffffff")).is_none()

    def test_key_includes_size_and_tint(self, cache):
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix("#ff0000"))
        cache.put(_PACK, "a.svg", 24, "#ffffff", _pix("#00ff00"))
        cache.put(_PACK, "a.svg", 64, "#000000", _pix("#0000ff"))

        assert_that(_centre(cache.get(_PACK, "a.svg", 64, "#ffffff"))).is_equal_to((255, 0, 0))
        assert_that(_centre(cache.get(_PACK, "a.svg", 24, "#ffffff"))).is_equal_to((0, 255, 0))
        assert_that(_centre(cache.get(_PACK, "a.svg", 64, "#000000"))).is_equal_to((0, 0, 255))
        assert_that(cache.get(_PACK, "a.svg", 32, "#ffffff")).is_none()
        assert_that(cache.get(_PACK, "a.svg", 64, "#123456")).is_none()

    def test_no_tint_is_its_own_entry(self, cache):
        cache.put(_PACK, "a.svg", 64, None, _pix("#ff00ff"))

        assert_that(cache.get(_PACK, "a.svg", 64, "#ffffff")).is_none()
        assert_that(_centre(cache.get(_PACK, "a.svg", 64, None))).is_equal_to((255, 0, 255))

    def test_disk_layout_matches_the_spec(self, cache, tmp_path):
        cache.put(_PACK, "sub/a.svg", 64, "#FFFFFF", _pix())

        (file,) = _files(tmp_path / "cache")

        relative = file.relative_to(tmp_path / "cache").parts
        assert_that(relative[:3]).is_equal_to((_PACK, "1.0.0", "64-ffffff"))
        assert_that(relative[3]).matches(r"^[0-9a-f]{32}\.png$")
        assert_that(relative[3]).is_equal_to(hashlib.sha256(b"sub/a.svg").hexdigest()[:32] + ".png")

    def test_memory_lru_evicts_the_oldest_but_disk_still_has_it(self, tmp_path, qapp):
        small = IconThumbnailCache(tmp_path / "c", max_memory=2)
        small.update_packs(_packs())
        for name, colour in (("a", "#ff0000"), ("b", "#00ff00"), ("c", "#0000ff")):
            small.put(_PACK, f"{name}.svg", 8, None, _pix(colour))

        assert_that(len(small._memory)).is_equal_to(2)
        evicted = small.get(_PACK, "a.svg", 8, None)
        assert evicted is not None
        assert_that(_centre(evicted)).is_equal_to((255, 0, 0))
        assert_that(len(small._memory)).is_equal_to(2)


class TestRobustness:
    def _put_and_find(self, cache: IconThumbnailCache, tmp_path: Path) -> Path:
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix())
        (file,) = _files(tmp_path / "cache")
        return file

    def test_corrupt_png_is_a_miss_and_is_deleted(self, tmp_path, qapp):
        first = IconThumbnailCache(tmp_path / "cache")
        first.update_packs(_packs())
        file = self._put_and_find(first, tmp_path)
        file.write_bytes(b"this is not a png")
        fresh = IconThumbnailCache(tmp_path / "cache")
        fresh.update_packs(_packs())

        assert_that(fresh.get(_PACK, "a.svg", 64, "#ffffff")).is_none()
        assert_that(file.exists()).is_false()

    def test_zero_byte_png_is_a_miss(self, tmp_path, qapp):
        first = IconThumbnailCache(tmp_path / "cache")
        first.update_packs(_packs())
        file = self._put_and_find(first, tmp_path)
        file.write_bytes(b"")
        fresh = IconThumbnailCache(tmp_path / "cache")
        fresh.update_packs(_packs())

        assert_that(fresh.get(_PACK, "a.svg", 64, "#ffffff")).is_none()
        assert_that(file.exists()).is_false()

    def test_corrupt_file_is_replaced_by_the_next_put(self, tmp_path, qapp):
        first = IconThumbnailCache(tmp_path / "cache")
        first.update_packs(_packs())
        file = self._put_and_find(first, tmp_path)
        file.write_bytes(b"junk")
        fresh = IconThumbnailCache(tmp_path / "cache")
        fresh.update_packs(_packs())
        assert_that(fresh.get(_PACK, "a.svg", 64, "#ffffff")).is_none()

        fresh.put(_PACK, "a.svg", 64, "#ffffff", _pix("#00ff00"))

        again = IconThumbnailCache(tmp_path / "cache")
        again.update_packs(_packs())
        assert_that(_centre(again.get(_PACK, "a.svg", 64, "#ffffff"))).is_equal_to((0, 255, 0))  # type: ignore[arg-type]

    def test_unwritable_root_does_not_raise_and_nothing_is_cached(self, tmp_path, qapp):
        blocker = tmp_path / "a-file"
        blocker.write_text("x")
        broken = IconThumbnailCache(blocker / "cache")  # a directory cannot be created below a file
        broken.update_packs(_packs())

        broken.put(_PACK, "a.svg", 64, "#ffffff", _pix())
        broken.put(_PACK, "b.svg", 64, "#ffffff", _pix())

        assert_that(broken.get(_PACK, "a.svg", 64, "#ffffff")).is_not_none()  # memory still serves it
        assert_that(blocker.read_text()).is_equal_to("x")

    def test_failed_writes_are_logged_once_not_per_icon(self, tmp_path, qapp, caplog):
        blocker = tmp_path / "a-file"
        blocker.write_text("x")
        broken = IconThumbnailCache(blocker / "cache")
        broken.update_packs(_packs())

        with caplog.at_level("DEBUG", logger="decker.client.icon_cache"):
            for index in range(5):
                broken.put(_PACK, f"{index}.svg", 64, "#ffffff", _pix())

        assert_that([r for r in caplog.records if "icon cache" in r.getMessage()]).is_length(1)

    def test_hostile_names_stay_inside_the_root(self, tmp_path, qapp):
        root = tmp_path / "sandbox" / "cache"
        hostile = IconThumbnailCache(root)
        hostile.update_packs(_packs(version="/abs/../..", pack="../../x"))

        for path in ("../../escape.svg", "/etc/passwd", "a\x00b.svg", "x" * 5000, "..", "sub/../../up.svg"):
            hostile.put("../../x", path, 64, "../../#bad", _pix())

        assert_that(list((tmp_path / "sandbox").iterdir())).is_equal_to([root])
        for file in _files(root):
            assert_that(file.resolve().is_relative_to(root.resolve())).described_as(str(file)).is_true()
        assert_that(list(tmp_path.iterdir())).is_equal_to([tmp_path / "sandbox"])

    def test_prune_failure_does_not_raise(self, cache, monkeypatch):
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix())

        def boom(*_a, **_k):
            raise OSError("busy")

        monkeypatch.setattr(shutil, "rmtree", boom)

        cache.update_packs(_packs(version="2.0.0"))  # would prune 1.0.0

        assert_that(cache.version_of(_PACK)).is_equal_to("2.0.0")


class TestInvalidation:
    def test_version_change_deletes_the_old_version_directory(self, cache, tmp_path):
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix())
        assert_that((tmp_path / "cache" / _PACK / "1.0.0").is_dir()).is_true()

        cache.update_packs(_packs(version="2.0.0"))

        assert_that((tmp_path / "cache" / _PACK / "1.0.0").exists()).is_false()
        assert_that(cache.get(_PACK, "a.svg", 64, "#ffffff")).is_none()  # the new version starts empty
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix("#00ff00"))
        assert_that((tmp_path / "cache" / _PACK / "2.0.0").is_dir()).is_true()

    def test_same_version_keeps_files(self, cache, tmp_path):
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix())
        before = _files(tmp_path / "cache")

        cache.update_packs(_packs())

        assert_that(_files(tmp_path / "cache")).is_equal_to(before)

    def test_uninstalled_pack_is_pruned(self, cache, tmp_path):
        cache.update_packs(_packs() + _packs(pack="com.y.other"))
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix())
        cache.put("com.y.other", "b.svg", 64, "#ffffff", _pix())

        cache.update_packs(_packs())

        assert_that((tmp_path / "cache" / "com.y.other").exists()).is_false()
        assert_that((tmp_path / "cache" / _PACK).is_dir()).is_true()
        assert_that(cache.get("com.y.other", "b.svg", 64, "#ffffff")).is_none()

    def test_removed_version_is_dropped_from_memory_too(self, cache):
        cache.put(_PACK, "a.svg", 64, "#ffffff", _pix())

        cache.update_packs(_packs(version="2.0.0"))

        assert_that(len(cache._memory)).is_zero()

    def test_pruning_with_no_cache_directory_yet_is_fine(self, tmp_path, qapp):
        empty = IconThumbnailCache(tmp_path / "never-created")

        empty.update_packs(_packs())

        assert_that((tmp_path / "never-created").exists()).is_false()


class TestDefaults:
    def test_default_root_follows_the_configured_prefix(self, tmp_path, qapp):
        original = paths._prefix
        try:
            paths.configure(tmp_path)
            lazy = IconThumbnailCache()
            lazy.update_packs(_packs())

            lazy.put(_PACK, "a.svg", 64, "#ffffff", _pix())

            files = _files(tmp_path / ".decker" / "cache" / "icons")
            assert_that(files).is_length(1)
            assert_that(re.search(r"/\.decker/cache/icons/", str(files[0]))).is_not_none()
        finally:
            paths._prefix = original

    def test_process_wide_instance_is_shared(self, monkeypatch, qapp):
        monkeypatch.setattr(module, "_INSTANCE", None)

        assert_that(icon_cache()).is_same_as(icon_cache())
        assert_that(icon_cache()).is_instance_of(IconThumbnailCache)


class TestPruningNeverFollowsSymlinks:
    """Pruning deletes cache directories; it must never delete anything a symlink points to."""

    def test_a_symlinked_kept_pack_directory_is_not_descended_into(self, tmp_path, qapp):
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "precious").mkdir(parents=True)
        (elsewhere / "precious" / "file.txt").write_text("keep me")
        root = tmp_path / "cache"
        root.mkdir()
        (root / _PACK).symlink_to(elsewhere, target_is_directory=True)
        cache = IconThumbnailCache(root)

        cache.update_packs(_packs(version="1"))

        assert_that((elsewhere / "precious" / "file.txt").read_text()).is_equal_to("keep me")
        assert_that((root / _PACK).is_symlink()).is_true()

    def test_a_symlinked_pack_that_was_uninstalled_loses_the_link_not_the_target(self, tmp_path, qapp):
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "precious").mkdir(parents=True)
        root = tmp_path / "cache"
        root.mkdir()
        (root / "com.gone.pack").symlink_to(elsewhere, target_is_directory=True)
        cache = IconThumbnailCache(root)

        cache.update_packs(_packs())

        assert_that((root / "com.gone.pack").exists()).is_false()
        assert_that((root / "com.gone.pack").is_symlink()).is_false()
        assert_that((elsewhere / "precious").is_dir()).is_true()

    def test_a_symlinked_old_version_directory_loses_the_link_not_the_target(self, tmp_path, qapp):
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "precious").mkdir(parents=True)
        root = tmp_path / "cache"
        (root / _PACK).mkdir(parents=True)
        (root / _PACK / "0.9.0").symlink_to(elsewhere, target_is_directory=True)
        cache = IconThumbnailCache(root)

        cache.update_packs(_packs(version="1.0.0"))

        assert_that((root / _PACK / "0.9.0").is_symlink()).is_false()
        assert_that((elsewhere / "precious").is_dir()).is_true()

    def test_one_bad_entry_does_not_stop_the_rest_of_the_prune(self, tmp_path, qapp):
        root = tmp_path / "cache"
        root.mkdir()
        (root / "a-stray-file").write_text("not ours")
        (root / "com.gone.one").mkdir()
        (root / "zz-link").symlink_to(tmp_path, target_is_directory=True)
        (root / "com.gone.two").mkdir()
        cache = IconThumbnailCache(root)

        cache.update_packs(_packs())

        assert_that((root / "com.gone.one").exists()).is_false()
        assert_that((root / "com.gone.two").exists()).is_false()
        assert_that((root / "a-stray-file").read_text()).is_equal_to("not ours")  # files are not ours to delete

    def test_a_directory_that_cannot_be_removed_does_not_stop_the_others(self, tmp_path, qapp, monkeypatch):
        root = tmp_path / "cache"
        root.mkdir()
        (root / "com.gone.one").mkdir()
        (root / "com.gone.two").mkdir()
        real = shutil.rmtree

        def flaky(path, *args, **kwargs):
            if Path(path).name == "com.gone.one":
                raise OSError("busy")
            real(path, *args, **kwargs)

        monkeypatch.setattr(shutil, "rmtree", flaky)
        IconThumbnailCache(root).update_packs(_packs())

        assert_that((root / "com.gone.two").exists()).is_false()
