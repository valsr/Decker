import base64
import json
from pathlib import Path

from assertpy import assert_that
from PyQt6.QtCore import QObject, pyqtSignal

from decker.client.icon_picker import (
    IconPackBrowserDialog,
    IconPickerWidget,
    copy_to_user_icons,
)


class TestCopyToUserIcons:
    def test_copies_file_into_user_icons_dir(self, tmp_path, monkeypatch):
        import decker.client.icon_picker as module  # pylint: disable=import-outside-toplevel

        dest_dir = tmp_path / "user-icons"
        monkeypatch.setattr(module, "user_icons_dir", lambda: dest_dir)
        monkeypatch.setattr(module, "ensure_asset_dirs", lambda: dest_dir.mkdir(parents=True, exist_ok=True))

        source = tmp_path / "icon.svg"
        source.write_text("<svg/>")

        result = copy_to_user_icons(source)

        assert_that(result).is_equal_to(dest_dir / "icon.svg")
        assert_that(result.read_text()).is_equal_to("<svg/>")


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

    def test_browse_icon_packs_forwards_choice(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        import decker.client.icon_picker as module  # pylint: disable=import-outside-toplevel

        class FakeDialog(QObject):
            icon_chosen = pyqtSignal(str, str)

            def exec(self):
                self.icon_chosen.emit("p", "a.svg")

        monkeypatch.setattr(module, "IconPackBrowserDialog", lambda *a, **k: FakeDialog())
        widget = IconPickerWidget()
        received: list[tuple[str, str]] = []
        widget.pack_icon_selected.connect(lambda p, n: received.append((p, n)))

        widget._browse_icon_packs()  # pylint: disable=protected-access

        assert_that(received).is_equal_to([("p", "a.svg")])


_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="red"/></svg>'


class FakeConnectionManager:
    def __init__(self, packs=None, icons=None):
        self.packs = packs if packs is not None else []
        self.icons = icons or {}
        self.calls: list[tuple] = []

    def call(self, method, *args):
        self.calls.append((method, *args))
        if method == "iconpacks_list":
            return json.dumps(self.packs)
        if method == "iconpack_icons":
            return json.dumps(self.icons.get(args[0], []))
        if method == "iconpack_icon":
            return base64.b64encode(_SVG).decode()
        return None


def _manager():
    packs = [{"id": "com.x/p", "name": "Pack A", "description": "", "plugin_id": "com.x", "icon_count": 2}]
    return FakeConnectionManager(packs, {"com.x/p": ["a.svg", "b.svg"]})


class TestIconPackBrowserDialog:
    def test_lists_packs_from_server(self, qapp):  # pylint: disable=unused-argument
        dialog = IconPackBrowserDialog(None, _manager())

        assert_that(dialog._pack_list.count()).is_equal_to(1)  # pylint: disable=protected-access
        assert_that(dialog._pack_list.item(0).text())  # type: ignore[union-attr]  # noqa.is_equal_to("Pack A")  # pylint: disable=protected-access

    def test_selecting_pack_lists_its_icons(self, qapp):  # pylint: disable=unused-argument
        dialog = IconPackBrowserDialog(None, _manager())

        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access

        assert_that(dialog._icon_list.count()).is_equal_to(2)  # pylint: disable=protected-access

    def test_icons_are_loaded_lazily_and_cached(self, qapp):  # pylint: disable=unused-argument
        cm = _manager()
        dialog = IconPackBrowserDialog(None, cm)
        assert_that([c for c in cm.calls if c[0] == "iconpack_icon"]).is_empty()

        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access
        dialog._pack_list.setCurrentRow(-1)  # pylint: disable=protected-access
        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access

        assert_that([c for c in cm.calls if c[0] == "iconpack_icon"]).is_length(2)

    def test_icon_choice_emits_pack_and_name(self, qapp):  # pylint: disable=unused-argument
        dialog = IconPackBrowserDialog(None, _manager())
        received: list[tuple[str, str]] = []
        dialog.icon_chosen.connect(lambda p, n: received.append((p, n)))
        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access

        dialog._on_icon_chosen(dialog._icon_list.item(1))  # type: ignore[arg-type]  # pylint: disable=protected-access

        assert_that(received).is_equal_to([("com.x/p", "b.svg")])

    def test_works_without_local_pack_files(self, qapp, monkeypatch):  # pylint: disable=unused-argument
        def fail(*_a, **_k):
            raise AssertionError("local filesystem touched")

        monkeypatch.setattr(Path, "iterdir", fail)
        monkeypatch.setattr(Path, "is_dir", fail)
        dialog = IconPackBrowserDialog(None, _manager())

        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access

        assert_that(dialog._icon_list.count()).is_equal_to(2)  # pylint: disable=protected-access

    def test_shows_error_when_server_unreachable(self, qapp):  # pylint: disable=unused-argument
        class Down:
            def call(self, *_a):
                return None

        dialog = IconPackBrowserDialog(None, Down())

        assert_that(dialog._pack_list.count()).is_zero()  # pylint: disable=protected-access
        assert_that(dialog._status.text()).contains("Couldn't load")  # pylint: disable=protected-access

    def test_shows_empty_state_without_packs(self, qapp):  # pylint: disable=unused-argument
        dialog = IconPackBrowserDialog(None, FakeConnectionManager([]))

        assert_that(dialog._status.text()).contains("No icon packs")  # pylint: disable=protected-access

    def test_unreadable_icon_falls_back_to_placeholder(self, qapp):  # pylint: disable=unused-argument
        cm = _manager()
        cm.call = lambda m, *a: ("!!" if m == "iconpack_icon" else FakeConnectionManager.call(cm, m, *a))
        dialog = IconPackBrowserDialog(None, cm)

        dialog._pack_list.setCurrentRow(0)  # pylint: disable=protected-access

        assert_that(dialog._icon_list.count()).is_equal_to(2)  # pylint: disable=protected-access
