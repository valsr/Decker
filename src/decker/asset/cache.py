"""In-memory LRU cache wrapping AssetRenderer.render_path to avoid redundant re-renders."""

from collections import OrderedDict
from pathlib import Path

from PIL import Image

from decker.asset.renderer import AssetRenderer

_DEFAULT_MAX_SIZE = 128


class AssetCache:
    """Caches rendered images keyed by (path, width, height); evicts least-recently-used.

    In-memory only today; designed so a persistent disk-backed cache can be swapped in
    later without changing callers.
    """

    def __init__(self, renderer: AssetRenderer | None = None, max_size: int = _DEFAULT_MAX_SIZE) -> None:
        self._renderer = renderer or AssetRenderer()
        self._max_size = max_size
        self._cache: OrderedDict[tuple[Path, int, int], Image.Image] = OrderedDict()

    def get(self, path: Path, width: int, height: int) -> Image.Image:
        """Return the rendered image for path at width x height, rendering and caching on miss."""
        key = (path, width, height)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        image = self._renderer.render_path(path, width, height)
        self._cache[key] = image
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return image

    def clear(self) -> None:
        """Drop all cached images."""
        self._cache.clear()
