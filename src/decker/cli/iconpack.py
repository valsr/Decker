"""Local filesystem operations for installing, listing, and removing icon packs.

Like cli/plugin.py, these never talk to the server — they only touch
~/.decker/assets/iconpacks/ and decker.db. A server restart is required to
pick up the change.
"""

from pathlib import Path

from decker.asset.iconpack import IconPackError, IconPackManager


def install(source: str | Path) -> Path:
    """Validate and install the icon pack at source. Raises IconPackError on failure."""
    return IconPackManager().install(source)


def list_installed() -> list[dict]:
    """Return metadata for every registered icon pack: uuid, name, version."""
    return IconPackManager().list_packs()


def remove(pack_uuid: str) -> None:
    """Remove the installed icon pack matching pack_uuid. Raises IconPackError if not found."""
    IconPackManager().remove(pack_uuid)


__all__ = ["install", "list_installed", "remove", "IconPackError"]
