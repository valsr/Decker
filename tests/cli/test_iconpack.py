import json

import pytest
from assertpy import assert_that

from decker.asset import iconpack as iconpack_core
from decker.asset.store import IconPackStore
from decker.cli import iconpack as iconpack_cli

_MANIFEST = {"Name": "My Pack", "Version": "1.0.0", "Author": "Someone"}
_ICONS = {"icon1": "icon1.svg"}


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    packs_dir = tmp_path / "iconpacks"
    db_path = tmp_path / "decker.db"
    monkeypatch.setattr(iconpack_core, "ICONPACKS_DIR", packs_dir)
    monkeypatch.setattr(iconpack_core, "IconPackStore", lambda: IconPackStore(db_path))
    return packs_dir


def _write_source_pack(tmp_path, name="MyPack.sdIconPack"):
    source_dir = tmp_path / name
    source_dir.mkdir()
    (source_dir / "manifest.json").write_text(json.dumps(_MANIFEST))
    (source_dir / "icons.json").write_text(json.dumps(_ICONS))
    return source_dir


class TestInstall:
    def test_installs_pack(self, tmp_path, _isolated_paths):
        source = _write_source_pack(tmp_path)
        dest = iconpack_cli.install(source)
        assert_that(dest).is_equal_to(_isolated_paths / "MyPack.sdIconPack")

    def test_invalid_pack_raises(self, tmp_path):
        bad = tmp_path / "not-a-pack"
        bad.mkdir()
        with pytest.raises(iconpack_cli.IconPackError):
            iconpack_cli.install(bad)


class TestListAndRemove:
    def test_list_returns_installed_pack(self, tmp_path):
        iconpack_cli.install(_write_source_pack(tmp_path))
        result = iconpack_cli.list_installed()
        assert_that(result).is_length(1)
        assert_that(result[0]["name"]).is_equal_to("My Pack")

    def test_remove_deletes_pack(self, tmp_path):
        iconpack_cli.install(_write_source_pack(tmp_path))
        pack_uuid = iconpack_cli.list_installed()[0]["uuid"]
        iconpack_cli.remove(pack_uuid)
        assert_that(iconpack_cli.list_installed()).is_empty()

    def test_remove_unknown_raises(self):
        with pytest.raises(iconpack_cli.IconPackError):
            iconpack_cli.remove("unknown")
