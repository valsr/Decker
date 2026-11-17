import json

from assertpy import assert_that

from decker.asset.iconpack import IconPackRegistry
from decker.plugin.icons import MAX_ICON_BYTES
from decker.plugin.loader import InstalledPlugin
from decker.plugin.manifest import PluginManifest


def _plugin(tmp_path, path="pack", plugin_id="com.t.p", pack_id="com.t.p.icons") -> InstalledPlugin:
    data = {
        "format": 1,
        "id": plugin_id,
        "name": "T",
        "version": "1.0.0",
        "author": "a",
        "description": "d",
        "contributes": {"icon_packs": [{"id": pack_id, "name": "Pack", "path": path}]},
    }
    manifest = PluginManifest.from_dict(data)
    return InstalledPlugin(manifest, tmp_path)


def _pack(tmp_path) -> None:
    pack = tmp_path / "pack"
    (pack / "sub").mkdir(parents=True)
    (pack / "a.png").write_bytes(b"png-a")
    (pack / "sub" / "b.svg").write_text("<svg/>")
    (pack / "notes.txt").write_text("x")
    (tmp_path / "manifest.json").write_text("{}")


def test_list_icons_finds_images(tmp_path):
    _pack(tmp_path)
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    assert_that(registry.list_icons("com.t.p.icons")).is_equal_to(["a.png", "sub/b.svg"])
    assert_that(registry.list_packs()).is_equal_to(
        [{"id": "com.t.p.icons", "name": "Pack", "description": "", "plugin_id": "com.t.p", "icon_count": 2}]
    )


def test_icons_json_orders_icons(tmp_path):
    _pack(tmp_path)
    (tmp_path / "pack" / "icons.json").write_text(json.dumps([{"path": "sub/b.svg"}, "a.png", "gone.png"]))
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    assert_that(registry.list_icons("com.t.p.icons")).is_equal_to(["sub/b.svg", "a.png"])


def test_read_icon_returns_bytes(tmp_path):
    _pack(tmp_path)
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    assert_that(registry.read_icon("com.t.p.icons", "a.png")).is_equal_to(b"png-a")
    assert_that(registry.read_icon("com.t.p.icons", "missing.png")).is_none()
    assert_that(registry.read_icon("unknown", "a.png")).is_none()
    assert_that(registry.read_icon("com.t.p.icons", "notes.txt")).is_none()


def test_read_icon_rejects_path_escape(tmp_path):
    _pack(tmp_path)
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    assert_that(registry.read_icon("com.t.p.icons", "../manifest.json")).is_none()


def test_read_icon_rejects_symlink_escape(tmp_path):
    _pack(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-secret.png"
    outside.write_bytes(b"secret")
    (tmp_path / "pack" / "link.png").symlink_to(outside)
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    assert_that(registry.read_icon("com.t.p.icons", "link.png")).is_none()
    assert_that(registry.list_icons("com.t.p.icons")).does_not_contain("link.png")


def test_read_icon_rejects_oversized(tmp_path):
    _pack(tmp_path)
    (tmp_path / "pack" / "big.png").write_bytes(b"x" * (MAX_ICON_BYTES + 1))
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    assert_that(registry.read_icon("com.t.p.icons", "big.png")).is_none()


def test_pack_path_escaping_plugin_is_refused(tmp_path):
    plugin_dir = tmp_path / "plugin"
    (tmp_path / "elsewhere").mkdir()
    plugin_dir.mkdir()
    failures: list[tuple[str, str]] = []
    registry = IconPackRegistry(on_failure=lambda pid, err: failures.append((pid, err)))
    registry.register(_plugin(plugin_dir, path="../elsewhere"))
    assert_that(registry.list_packs()).is_empty()
    assert_that(failures).is_length(1)
    assert_that(failures[0][1]).contains("outside")


def test_missing_folder_and_duplicate_id_are_refused(tmp_path):
    _pack(tmp_path)
    failures: list[tuple[str, str]] = []
    registry = IconPackRegistry(on_failure=lambda pid, err: failures.append((pid, err)))
    registry.register(_plugin(tmp_path, path="nope"))
    registry.register(_plugin(tmp_path))
    registry.register(_plugin(tmp_path))
    assert_that(failures).is_length(2)
    assert_that(registry.list_packs()).is_length(1)


def test_unregister_removes_pack(tmp_path):
    _pack(tmp_path)
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    registry.unregister("com.t.p")
    assert_that(registry.list_packs()).is_empty()
    assert_that(registry.list_icons("com.t.p.icons")).is_empty()


def test_read_icon_with_nul_byte_returns_none(tmp_path):
    _pack(tmp_path)
    registry = IconPackRegistry()
    registry.register(_plugin(tmp_path))
    assert_that(registry.read_icon("com.t.p.icons", "a\0.png")).is_none()
