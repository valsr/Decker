"""Installs, lists, removes, and discovers icon packs on disk."""

import logging
import shutil
import uuid as uuid_lib
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from decker.asset.manifest import (
    IconPackManifest,
    IconPackValidationError,
    validate_icons_json,
)
from decker.asset.paths import ICONPACKS_DIR, ensure_asset_dirs
from decker.asset.store import IconPackStore
from decker.common.manager import Manager

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext


class IconPackError(Exception):
    """An icon pack operation failed."""


class IconPackManager(Manager):
    """Handles icon pack install/list/remove and manual drop-in detection."""

    def __init__(self, store: IconPackStore | None = None, packs_dir: Path | None = None) -> None:
        self._store = store or IconPackStore()
        self._packs_dir = packs_dir or ICONPACKS_DIR

    def create(self, context: "ServerContext") -> None:
        """Ensure asset directories exist and register any on-disk drop-ins."""
        self._packs_dir.mkdir(parents=True, exist_ok=True)
        ensure_asset_dirs()
        self.discover_manual_dropins()

    def destroy(self) -> None:
        """No-op: IconPackManager holds no open resources."""

    def install(self, source: str | Path) -> Path:
        """Install a .sdIconPack folder or .streamDeckIconPack ZIP. Raises IconPackError on failure."""
        source_path = Path(source)
        if source_path.is_file() and source_path.suffix == ".streamDeckIconPack":
            return self._install_zip(source_path)
        if source_path.is_dir() and source_path.name.endswith(".sdIconPack"):
            return self._install_folder(source_path)
        raise IconPackError(f"{source_path} is not a .sdIconPack folder or .streamDeckIconPack file")

    def list_packs(self) -> list[dict]:
        """Return all registered icon packs."""
        return self._store.list_packs()

    def remove(self, pack_uuid: str) -> None:
        """Remove an installed icon pack from disk and the registry. Raises IconPackError if unknown."""
        pack = self._store.get_pack(pack_uuid)
        if pack is None:
            raise IconPackError(f"no installed icon pack found with uuid {pack_uuid!r}")
        shutil.rmtree(pack["path"], ignore_errors=True)
        self._store.remove_pack(pack_uuid)

    def discover_manual_dropins(self) -> None:
        """Register any .sdIconPack folders present on disk but not yet in the store."""
        registered_paths = {pack["path"] for pack in self._store.list_packs()}
        for entry in self._packs_dir.iterdir():
            if not entry.is_dir() or not entry.name.endswith(".sdIconPack") or str(entry) in registered_paths:
                continue
            try:
                self._register(entry)
            except IconPackValidationError as exc:
                logging.warning("Skipping invalid icon pack drop-in %s: %s", entry, exc)

    def _install_zip(self, source_path: Path) -> Path:
        dest_dir = self._packs_dir / f"{source_path.stem}.sdIconPack"
        if dest_dir.exists():
            raise IconPackError(f"an icon pack is already installed at {dest_dir}")
        with zipfile.ZipFile(source_path) as zip_file:
            zip_file.extractall(dest_dir)
        return self._register_new(dest_dir)

    def _install_folder(self, source_path: Path) -> Path:
        dest_dir = self._packs_dir / source_path.name
        if dest_dir.exists():
            raise IconPackError(f"an icon pack is already installed at {dest_dir}")
        shutil.copytree(source_path, dest_dir)
        return self._register_new(dest_dir)

    def _register_new(self, dest_dir: Path) -> Path:
        """Register a pack we just copied/extracted ourselves; clean up dest_dir if invalid."""
        try:
            self._register(dest_dir)
        except IconPackValidationError as exc:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise IconPackError(str(exc)) from exc
        return dest_dir

    def _register(self, dest_dir: Path) -> None:
        manifest = IconPackManifest.load(dest_dir / "manifest.json")
        validate_icons_json(dest_dir / "icons.json")
        self._store.add_pack(str(uuid_lib.uuid4()), manifest.name, manifest.version, str(dest_dir))
