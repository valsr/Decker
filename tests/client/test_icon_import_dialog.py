import base64
import io
import json
from pathlib import Path
from typing import Any

from assertpy import assert_that
from PIL import Image
from PyQt6.QtWidgets import QApplication

from decker.client.icon_import_dialog import IconImportDialog


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(buffer, "PNG")
    return buffer.getvalue()


class FakeServer:
    def __init__(self, import_result: dict[str, Any] | None = None, preview: Any = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.import_result = import_result or {
            "ok": True,
            "id": "cat",
            "file": "cat.png",
            "error": "",
            "suggestion": "",
        }
        self.preview = base64.b64encode(_png_bytes()).decode() if preview is None else preview

    def call(self, method: str, *args: Any) -> Any:
        self.calls.append((method, *args))
        if method == "icon_import_suggest":
            return "cat"
        if method == "icon_import_preview":
            return self.preview
        if method == "icon_import":
            return json.dumps(self.import_result)
        return None

    def named(self, method: str) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if c[0] == method]


def _file(tmp_path: Path, name: str = "Cat.png", data: bytes | None = None) -> Path:
    path = tmp_path / name
    path.write_bytes(_png_bytes() if data is None else data)
    return path


class TestIconImportDialog:
    def test_dialog_prefills_the_id_from_the_suggestion(self, qapp: QApplication, tmp_path: Path) -> None:
        server = FakeServer()

        dialog = IconImportDialog(None, server, "Cat.png", _png_bytes())

        assert_that(server.named("icon_import_suggest")).is_equal_to([("icon_import_suggest", "Cat")])
        assert_that(dialog._id_edit.text()).is_equal_to("cat")  # pylint: disable=protected-access

    def test_import_sends_id_bytes_and_options_and_emits_imported(self, qapp: QApplication, tmp_path: Path) -> None:
        server = FakeServer()
        path = _file(tmp_path)
        dialog = IconImportDialog(None, server, "Cat.png", path.read_bytes())
        received: list[str] = []
        dialog.imported.connect(received.append)
        dialog._fit.setCurrentText("Stretch")  # pylint: disable=protected-access
        dialog._interpolation.setCurrentText("Lanczos")  # pylint: disable=protected-access

        dialog._import_button.click()  # pylint: disable=protected-access

        method, name, filename, data, options = server.named("icon_import")[0]
        assert_that((method, name, filename)).is_equal_to(("icon_import", "cat", "Cat.png"))
        assert_that(data).is_equal_to(path.read_bytes())
        assert_that(json.loads(options)).is_equal_to({"fit": "stretch", "interpolation": "lanczos"})
        assert_that(received).is_equal_to(["cat.png"])
        assert_that(dialog.result()).is_equal_to(1)

    def test_duplicate_shows_error_and_use_suggestion_fills_the_id(self, qapp: QApplication, tmp_path: Path) -> None:
        server = FakeServer(
            {"ok": False, "id": "cat", "file": "", "error": "cat already exists", "suggestion": "cat-2"}
        )
        dialog = IconImportDialog(None, server, "Cat.png", _png_bytes())
        received: list[str] = []
        dialog.imported.connect(received.append)

        dialog._import_button.click()  # pylint: disable=protected-access

        assert_that(received).is_empty()
        assert_that(dialog._error.text()).is_equal_to("cat already exists")  # pylint: disable=protected-access
        use = dialog._use_suggestion  # pylint: disable=protected-access
        assert_that(use.isHidden()).is_false()
        assert_that(use.text()).is_equal_to("Use cat-2")
        use.click()
        assert_that(dialog._id_edit.text()).is_equal_to("cat-2")  # pylint: disable=protected-access

    def test_svg_hides_fit_and_interpolation(self, qapp: QApplication, tmp_path: Path) -> None:
        svg = _file(tmp_path, "logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")

        dialog = IconImportDialog(None, FakeServer(), "logo.svg", svg.read_bytes())
        dialog.show()

        assert_that(dialog._fit.isVisible()).is_false()  # pylint: disable=protected-access
        assert_that(dialog._interpolation.isVisible()).is_false()  # pylint: disable=protected-access

    def test_options_change_refreshes_the_preview(self, qapp: QApplication, tmp_path: Path) -> None:
        server = FakeServer()
        dialog = IconImportDialog(None, server, "Cat.png", _png_bytes())
        before = len(server.named("icon_import_preview"))

        dialog._fit.setCurrentText("Stretch")  # pylint: disable=protected-access
        dialog._preview_timer.timeout.emit()  # pylint: disable=protected-access

        calls = server.named("icon_import_preview")
        assert_that(calls).is_length(before + 1)
        assert_that(json.loads(calls[-1][3])["fit"]).is_equal_to("stretch")
        assert_that(dialog._preview.pixmap().isNull()).is_false()  # pylint: disable=protected-access

    def test_refused_preview_shows_a_placeholder_not_an_exception(self, qapp: QApplication, tmp_path: Path) -> None:
        dialog = IconImportDialog(None, FakeServer(preview=""), "Cat.png", _png_bytes())

        assert_that(dialog._preview.text()).is_not_empty()  # pylint: disable=protected-access
