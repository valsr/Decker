import json
import zipfile

import pytest
from assertpy import assert_that

from decker.asset.iconpack import IconPackError, IconPackManager
from decker.asset.store import IconPackStore

_MANIFEST = {"Name": "My Pack", "Version": "1.0.0", "Author": "Someone"}
_ICONS = {"icon1": "icon1.svg"}


def _make_manager(tmp_path):
    store = IconPackStore(tmp_path / "decker.db")
    packs_dir = tmp_path / "iconpacks"
    return IconPackManager(store=store, packs_dir=packs_dir), store, packs_dir


def _write_source_pack(tmp_path, name="MyPack.sdIconPack"):
    source_dir = tmp_path / name
    source_dir.mkdir()
    (source_dir / "manifest.json").write_text(json.dumps(_MANIFEST))
    (source_dir / "icons.json").write_text(json.dumps(_ICONS))
    return source_dir


class TestInstallFolder:
    def test_installs_sdiconpack_folder(self, tmp_path):
        manager, store, packs_dir = _make_manager(tmp_path)
        source = _write_source_pack(tmp_path)

        dest = manager.install(source)

        assert_that(dest).is_equal_to(packs_dir / "MyPack.sdIconPack")
        assert_that(store.list_packs()).is_length(1)

    def test_rejects_non_sdiconpack_directory(self, tmp_path):
        manager, _, _ = _make_manager(tmp_path)
        source = tmp_path / "not-a-pack"
        source.mkdir()
        with pytest.raises(IconPackError):
            manager.install(source)

    def test_invalid_manifest_raises_and_cleans_up(self, tmp_path):
        manager, store, packs_dir = _make_manager(tmp_path)
        source = tmp_path / "Bad.sdIconPack"
        source.mkdir()
        (source / "manifest.json").write_text(json.dumps({"Name": "Missing fields"}))
        (source / "icons.json").write_text(json.dumps(_ICONS))

        with pytest.raises(IconPackError):
            manager.install(source)

        assert_that(store.list_packs()).is_empty()
        assert_that((packs_dir / "Bad.sdIconPack").exists()).is_false()

    def test_duplicate_install_raises(self, tmp_path):
        manager, _, _ = _make_manager(tmp_path)
        source = _write_source_pack(tmp_path)
        manager.install(source)
        with pytest.raises(IconPackError, match="already installed"):
            manager.install(source)


class TestInstallZip:
    def test_installs_streamdeckiconpack_zip(self, tmp_path):
        manager, store, packs_dir = _make_manager(tmp_path)
        zip_path = tmp_path / "MyPack.streamDeckIconPack"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(_MANIFEST))
            zf.writestr("icons.json", json.dumps(_ICONS))

        dest = manager.install(zip_path)

        assert_that(dest).is_equal_to(packs_dir / "MyPack.sdIconPack")
        assert_that(store.list_packs()).is_length(1)


class TestListAndRemove:
    def test_list_returns_installed_packs(self, tmp_path):
        manager, _, _ = _make_manager(tmp_path)
        manager.install(_write_source_pack(tmp_path))
        assert_that(manager.list_packs()).is_length(1)

    def test_remove_deletes_from_disk_and_store(self, tmp_path):
        manager, store, packs_dir = _make_manager(tmp_path)
        manager.install(_write_source_pack(tmp_path))
        pack_uuid = store.list_packs()[0]["uuid"]

        manager.remove(pack_uuid)

        assert_that(store.list_packs()).is_empty()
        assert_that((packs_dir / "MyPack.sdIconPack").exists()).is_false()

    def test_remove_unknown_uuid_raises(self, tmp_path):
        manager, _, _ = _make_manager(tmp_path)
        with pytest.raises(IconPackError):
            manager.remove("unknown")


class TestDiscoverManualDropins:
    def test_detects_unregistered_folder(self, tmp_path):
        manager, store, packs_dir = _make_manager(tmp_path)
        dropin = packs_dir / "Dropped.sdIconPack"
        dropin.mkdir()
        (dropin / "manifest.json").write_text(json.dumps(_MANIFEST))
        (dropin / "icons.json").write_text(json.dumps(_ICONS))

        manager.discover_manual_dropins()

        assert_that(store.list_packs()).is_length(1)

    def test_skips_already_registered_pack(self, tmp_path):
        manager, store, packs_dir = _make_manager(tmp_path)
        manager.install(_write_source_pack(tmp_path))

        manager.discover_manual_dropins()

        assert_that(store.list_packs()).is_length(1)

    def test_invalid_dropin_is_skipped_not_deleted(self, tmp_path):
        manager, store, packs_dir = _make_manager(tmp_path)
        dropin = packs_dir / "Bad.sdIconPack"
        dropin.mkdir()
        (dropin / "manifest.json").write_text(json.dumps({"Name": "Missing fields"}))

        manager.discover_manual_dropins()

        assert_that(store.list_packs()).is_empty()
        assert_that(dropin.exists()).is_true()
