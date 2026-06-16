from unittest.mock import MagicMock

from assertpy import assert_that
from PyQt6.QtWidgets import QDialog

from decker.client.icon_picker import (
    IconPackBrowserDialog,
    IconPickerWidget,
    copy_to_user_icons,
    list_pack_icons,
)


class TestCopyToUserIcons:
    def test_copies_file_into_user_icons_dir(self, tmp_path, monkeypatch):
        import decker.client.icon_picker as module  # pylint: disable=import-outside-toplevel

        dest_dir = tmp_path / "user-icons"
        monkeypatch.setattr(module, "USER_ICONS_DIR", dest_dir)
        monkeypatch.setattr(module, "ensure_asset_dirs", lambda: dest_dir.mkdir(parents=True, exist_ok=True))

        source = tmp_path / "icon.svg"
        source.write_text("<svg/>")

        result = copy_to_user_icons(source)

        assert_that(result).is_equal_to(dest_dir / "icon.svg")
        assert_that(result.read_text()).is_equal_to("<svg/>")


class TestListPackIcons:
    def test_returns_image_files_sorted(self, tmp_path):
        (tmp_path / "b.png").write_bytes(b"x")
        (tmp_path / "a.svg").write_text("<svg/>")
        (tmp_path / "notes.txt").write_text("ignore me")

        result = list_pack_icons(tmp_path)

        assert_that(result).is_equal_to([tmp_path / "a.svg", tmp_path / "b.png"])

    def test_returns_empty_list_for_missing_dir(self, tmp_path):
        assert_that(list_pack_icons(tmp_path / "missing")).is_equal_to([])


class TestIconPickerWidget:
    def test_choose_file_emits_icon_selected(self, qapp, tmp_path, monkeypatch):  # pylint: disable=unused-argument
        import decker.client.icon_picker as module  # pylint: disable=import-outside-toplevel

        source = tmp_path / "icon.png"
        source.write_bytes(b"x")
        monkeypatch.setattr(module.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(source), "")))
        monkeypatch.setattr(module, "copy_to_user_icons", lambda path: tmp_path / "copied" / path.name)

        widget = IconPickerWidget()
        received: list[str] = []
        widget.icon_selected.connect(received.append)

        widget._choose_file()  # pylint: disable=protected-access

        assert_that(received).is_equal_to([str(tmp_path / "copied" / "icon.png")])

    def test_choose_file_emits_nothing_when_dialog_cancelled(
        self, qapp, monkeypatch
    ):  # pylint: disable=unused-argument
        import decker.client.icon_picker as module  # pylint: disable=import-outside-toplevel

        monkeypatch.setattr(module.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
        widget = IconPickerWidget()
        received: list[str] = []
        widget.icon_selected.connect(received.append)

        widget._choose_file()  # pylint: disable=protected-access

        assert_that(received).is_empty()

    def test_browse_icon_packs_emits_selected_path_on_accept(
        self, qapp, monkeypatch
    ):  # pylint: disable=unused-argument
        import decker.client.icon_picker as module  # pylint: disable=import-outside-toplevel

        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = QDialog.DialogCode.Accepted
        fake_dialog.selected_path = "icon.svg"
        monkeypatch.setattr(module, "IconPackBrowserDialog", lambda *a, **k: fake_dialog)

        widget = IconPickerWidget()
        received: list[str] = []
        widget.icon_selected.connect(received.append)

        widget._browse_icon_packs()  # pylint: disable=protected-access

        assert_that(received).is_equal_to(["icon.svg"])


class TestIconPackBrowserDialog:
    def test_populates_packs_from_manager(self, qapp):  # pylint: disable=unused-argument
        manager = MagicMock()
        manager.list_packs.return_value = [{"name": "Pack A", "path": "/path/a"}]

        dialog = IconPackBrowserDialog(icon_pack_manager=manager)

        assert_that(dialog._pack_list.count()).is_equal_to(1)  # pylint: disable=protected-access
        pack_item = dialog._pack_list.item(0)  # pylint: disable=protected-access
        assert pack_item is not None
        assert_that(pack_item.text()).is_equal_to("Pack A")

    def test_selecting_pack_populates_icons(self, qapp, tmp_path):  # pylint: disable=unused-argument
        pack_dir = tmp_path / "PackA.sdIconPack"
        pack_dir.mkdir()
        (pack_dir / "icon1.svg").write_text("<svg/>")
        manager = MagicMock()
        manager.list_packs.return_value = [{"name": "Pack A", "path": str(pack_dir)}]

        dialog = IconPackBrowserDialog(icon_pack_manager=manager)
        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access

        assert_that(dialog._icon_list.count()).is_equal_to(1)  # pylint: disable=protected-access

    def test_double_clicking_icon_accepts_with_selected_path(self, qapp, tmp_path):  # pylint: disable=unused-argument
        pack_dir = tmp_path / "PackA.sdIconPack"
        pack_dir.mkdir()
        (pack_dir / "icon1.svg").write_text("<svg/>")
        manager = MagicMock()
        manager.list_packs.return_value = [{"name": "Pack A", "path": str(pack_dir)}]

        dialog = IconPackBrowserDialog(icon_pack_manager=manager)
        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access
        item = dialog._icon_list.item(0)  # pylint: disable=protected-access
        assert item is not None

        dialog._on_icon_chosen(item)  # pylint: disable=protected-access

        assert_that(dialog.selected_path).is_equal_to(pack_dir / "icon1.svg")
