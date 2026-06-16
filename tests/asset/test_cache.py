from unittest.mock import MagicMock

from assertpy import assert_that
from PIL import Image

from decker.asset.cache import AssetCache


def _make_renderer():
    renderer = MagicMock()
    renderer.render_path.return_value = Image.new("RGBA", (10, 10))
    return renderer


class TestAssetCache:
    def test_cache_miss_invokes_renderer(self, tmp_path):
        renderer = _make_renderer()
        cache = AssetCache(renderer=renderer)
        path = tmp_path / "icon.svg"

        cache.get(path, 10, 10)

        renderer.render_path.assert_called_once_with(path, 10, 10)

    def test_cache_hit_does_not_reinvoke_renderer(self, tmp_path):
        renderer = _make_renderer()
        cache = AssetCache(renderer=renderer)
        path = tmp_path / "icon.svg"

        cache.get(path, 10, 10)
        cache.get(path, 10, 10)

        renderer.render_path.assert_called_once()

    def test_different_size_is_a_separate_cache_entry(self, tmp_path):
        renderer = _make_renderer()
        cache = AssetCache(renderer=renderer)
        path = tmp_path / "icon.svg"

        cache.get(path, 10, 10)
        cache.get(path, 20, 20)

        assert_that(renderer.render_path.call_count).is_equal_to(2)

    def test_evicts_least_recently_used_beyond_max_size(self, tmp_path):
        renderer = _make_renderer()
        cache = AssetCache(renderer=renderer, max_size=2)
        a, b, c = tmp_path / "a.svg", tmp_path / "b.svg", tmp_path / "c.svg"

        cache.get(a, 1, 1)
        cache.get(b, 1, 1)
        cache.get(c, 1, 1)  # evicts a
        cache.get(a, 1, 1)  # miss again

        assert_that(renderer.render_path.call_count).is_equal_to(4)

    def test_clear_drops_all_entries(self, tmp_path):
        renderer = _make_renderer()
        cache = AssetCache(renderer=renderer)
        path = tmp_path / "icon.svg"
        cache.get(path, 10, 10)

        cache.clear()
        cache.get(path, 10, 10)

        assert_that(renderer.render_path.call_count).is_equal_to(2)
