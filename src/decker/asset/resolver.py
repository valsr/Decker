"""Resolves extension-less manifest icon paths to a concrete file on disk."""

from pathlib import Path

_EXTENSIONS_IN_PRIORITY_ORDER = (".svg", ".png", "@2x.png", ".jpg", ".jpeg")


class AssetResolver:
    """Tries known extensions, in priority order, for an extension-less base path."""

    def resolve(self, base_path: Path) -> Path | None:
        """Return the first existing variant of base_path, or None if none exist."""
        for suffix in _EXTENSIONS_IN_PRIORITY_ORDER:
            candidate = base_path.parent / f"{base_path.name}{suffix}"
            if candidate.exists():
                return candidate
        return None
