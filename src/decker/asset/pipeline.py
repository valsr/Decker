"""Orchestrates the multi-level key-image resolution pipeline."""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from decker.asset.cache import AssetCache
from decker.asset.paths import DEFAULT_KEY_SVG
from decker.asset.renderer import AssetRenderer
from decker.asset.resolver import AssetResolver
from decker.asset.store import IconPackStore


@dataclass(frozen=True)
class AssetResolutionRequest:
    """Inputs for one key-image resolution: target size plus every fallback-chain source."""

    context_id: str
    width: int
    height: int
    runtime_override: bytes | None = None
    manifest_state_image: Path | None = None
    plugin_icon: Path | None = None


class AssetPipeline:
    """Resolves the image to show on a key, in priority order:

    1. an active runtime setImage() override
    2. a user-assigned icon (decker.db)
    3. the action's per-state manifest icon
    4. the plugin's top-level manifest icon
    5. the bundled default-key.svg fallback
    """

    def __init__(
        self,
        store: IconPackStore | None = None,
        resolver: AssetResolver | None = None,
        cache: AssetCache | None = None,
        renderer: AssetRenderer | None = None,
    ) -> None:
        self._store = store or IconPackStore()
        self._resolver = resolver or AssetResolver()
        self._cache = cache or AssetCache()
        self._renderer = renderer or AssetRenderer()

    def resolve(self, request: AssetResolutionRequest) -> Image.Image:
        """Return the resolved key image at the requested size, per the priority order above."""
        width, height = request.width, request.height

        if request.runtime_override is not None:
            rendered = self._renderer.render_bytes(request.runtime_override, width, height)
            if rendered is not None:
                return rendered

        user_icon = self._store.get_user_icon(request.context_id)
        if user_icon is not None:
            return self._cache.get(Path(user_icon), width, height)

        for base_path in (request.manifest_state_image, request.plugin_icon):
            if base_path is None:
                continue
            resolved = self._resolver.resolve(base_path)
            if resolved is not None:
                return self._cache.get(resolved, width, height)

        return self._cache.get(DEFAULT_KEY_SVG, width, height)
