import json

import pytest
from assertpy import assert_that
from PyQt6.QtCore import QByteArray, QEvent, QMimeData, QPointF, Qt
from PyQt6.QtGui import QColor, QDropEvent, QEnterEvent, QFocusEvent, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import decker.client.widgets.button_grid as button_grid_module
from decker.client.themes import BUNDLED, render_stylesheet
from decker.client.widgets.button_grid import ButtonGridWidget, KeyButtonWidget
from decker.common.model import KeyInfo


def _make_keys(count: int, rows: int = 3, cols: int = 5) -> list[KeyInfo]:
    keys = []
    for i in range(count):
        keys.append(KeyInfo(row=i // cols, col=i % cols, pixel_width=72, pixel_height=72, type="key"))
    return keys


class TestButtonGridWidget:
    def test_build_creates_expected_number_of_buttons(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(15))
        assert_that(grid.key_count).is_equal_to(15)
        assert_that(grid._grid_layout.count()).is_equal_to(15)  # pylint: disable=protected-access

    def test_build_rebuilds_grid(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.build(_make_keys(8))
        assert_that(grid._grid_layout.count()).is_equal_to(8)  # pylint: disable=protected-access

    def _button(self, grid: ButtonGridWidget, index: int) -> KeyButtonWidget:
        layout_item = grid._grid_layout.itemAt(index)  # pylint: disable=protected-access
        assert layout_item is not None
        button = layout_item.widget()
        assert isinstance(button, KeyButtonWidget)
        return button

    def test_clicking_key_emits_key_edit_requested_only(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        pressed: list[int] = []
        edits: list[int] = []
        grid.key_pressed.connect(pressed.append)
        grid.key_edit_requested.connect(edits.append)

        self._button(grid, 2).click()

        assert_that(edits).is_equal_to([2])
        assert_that(pressed).is_empty()

    def test_clicking_the_play_button_emits_key_pressed_only(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        pressed: list[int] = []
        edits: list[int] = []
        grid.key_pressed.connect(pressed.append)
        grid.key_edit_requested.connect(edits.append)

        self._button(grid, 4)._run_button.click()  # pylint: disable=protected-access

        assert_that(pressed).is_equal_to([4])
        assert_that(edits).is_empty()

    def test_every_key_gets_a_play_button(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))

        for index in range(6):
            assert_that(
                self._button(grid, index)._run_button.toolTip()
            ).is_equal_to(  # pylint: disable=protected-access
                "Run this key"
            )

    def test_rebuilding_while_hovered_leaves_no_stale_play_button(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.show()
        _enter(self._button(grid, 2))
        grid.build(_make_keys(4))
        qapp.processEvents()

        assert_that(grid.key_count).is_equal_to(4)
        for index in range(4):
            assert_that(
                self._button(grid, index)._run_button.isVisible()
            ).is_false()  # pylint: disable=protected-access

    def test_set_key_label_updates_button_text(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.set_key_label(0, "42")
        button = grid._buttons.get(0)  # pylint: disable=protected-access
        assert button is not None
        assert_that(button.text()).is_equal_to("42")

    def test_set_key_label_for_missing_key_does_not_raise(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.set_key_label(99, "x")  # should not raise


class TestKeyButtonWidget:
    def test_set_label_updates_display(self, qapp):  # pylint: disable=unused-argument
        btn = KeyButtonWidget(0, KeyInfo(row=0, col=0, pixel_width=72, pixel_height=72, type="key"))
        btn.set_label("99")
        assert_that(btn.text()).is_equal_to("99")

    def test_default_text_is_key_number(self, qapp):  # pylint: disable=unused-argument
        btn = KeyButtonWidget(4, KeyInfo(row=0, col=4, pixel_width=72, pixel_height=72, type="key"))
        assert_that(btn.text()).is_equal_to("5")


def _key(index: int = 3) -> KeyButtonWidget:
    return KeyButtonWidget(index, KeyInfo(row=0, col=0, pixel_width=72, pixel_height=72, type="key"))


def _enter(widget) -> None:
    QApplication.sendEvent(widget, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))


def _leave(widget) -> None:
    QApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))


class TestKeyPlayButton:  # pylint: disable=protected-access,unused-argument
    def test_play_button_is_hidden_until_the_pointer_enters(self, qapp):
        button = _key()
        button.show()

        assert_that(button._run_button.isVisible()).is_false()

    def test_play_button_shows_on_enter_and_hides_on_leave(self, qapp):
        button = _key()
        button.show()

        _enter(button)
        assert_that(button._run_button.isVisible()).is_true()
        _leave(button)
        assert_that(button._run_button.isVisible()).is_false()

    def test_play_button_sits_in_the_top_right_corner(self, qapp):
        button = _key()
        button.show()

        geometry = button._run_button.geometry()

        assert_that((geometry.width(), geometry.height())).is_equal_to((30, 30))
        assert_that(button.width() - geometry.right() - 1).is_equal_to(4)
        assert_that(geometry.top()).is_equal_to(4)

    def test_play_button_has_a_tooltip_and_something_to_look_at(self, qapp):
        play_button = _key()._run_button

        assert_that(play_button.toolTip()).is_equal_to("Run this key")
        assert_that(play_button.icon().isNull() and not play_button.text()).is_false()

    def test_play_button_click_emits_run_clicked_with_the_index_and_not_edit_clicked(self, qapp):
        button = _key(7)
        runs: list[int] = []
        edits: list[int] = []
        button.run_clicked.connect(runs.append)
        button.edit_clicked.connect(edits.append)

        button._run_button.click()

        assert_that(runs).is_equal_to([7])
        assert_that(edits).is_empty()

    def test_key_click_emits_edit_clicked_and_not_run_clicked(self, qapp):
        button = _key(7)
        runs: list[int] = []
        edits: list[int] = []
        button.run_clicked.connect(runs.append)
        button.edit_clicked.connect(edits.append)

        button.click()

        assert_that(edits).is_equal_to([7])
        assert_that(runs).is_empty()

    def test_pressing_the_play_button_starts_its_long_press_timer(self, qapp):
        button = _key()
        button.show()
        _enter(button)

        QTest.mousePress(button._run_button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]

        assert_that(button._run_button._long_press_timer.isActive()).is_true()
        QTest.mouseRelease(button._run_button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]
        assert_that(button._run_button._long_press_timer.isActive()).is_false()

    def test_holding_the_play_button_emits_long_pressed_and_no_run_click(self, qapp):
        button = _key(3)
        button.show()
        _enter(button)
        long_presses: list[int] = []
        runs: list[int] = []
        button.long_pressed.connect(long_presses.append)
        button.run_clicked.connect(runs.append)

        QTest.mousePress(button._run_button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]
        button._run_button._long_press_timer.timeout.emit()
        QTest.mouseRelease(button._run_button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]

        assert_that(long_presses).is_equal_to([3])
        assert_that(runs).is_empty()

    def test_a_mouse_press_on_the_key_never_starts_a_long_press(self, qapp):
        button = _key()
        button.show()
        long_presses: list[int] = []
        button.long_pressed.connect(long_presses.append)

        QTest.mousePress(button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]

        assert_that(long_presses).is_empty()

    def test_play_button_does_not_swallow_drops(self, qapp):
        button = _key(4)
        button.show()
        dropped: list[tuple[int, object]] = []
        button.action_dropped.connect(lambda i, d: dropped.append((i, d)))
        mime = QMimeData()
        mime.setData("application/x-decker-action", QByteArray(json.dumps({"plugin_uuid": "p"}).encode()))
        center = QPointF(button._run_button.geometry().center())

        event = QDropEvent(
            center, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
        button.dropEvent(event)

        assert_that(button._run_button.acceptDrops()).is_false()  # so Qt hands the drop to the key
        assert_that(dropped).is_equal_to([(4, {"plugin_uuid": "p"})])


class TestPlayButtonTheming:  # pylint: disable=protected-access,unused-argument
    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_glyph_fits_the_play_button_under_the_bundled_theme(self, qapp, theme):
        button = _key()
        button.setStyleSheet(render_stylesheet(BUNDLED[theme]))
        button.show()
        qapp.processEvents()

        hint = button._run_button.sizeHint()

        # The global QToolButton padding used to leave ~6px for a 10px glyph, clipping it to a smudge.
        assert_that(hint.width()).described_as(f"{theme} width").is_less_than_or_equal_to(30)
        assert_that(hint.height()).described_as(f"{theme} height").is_less_than_or_equal_to(30)

    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_play_button_has_its_own_background_so_it_reads_over_a_key_image(self, qapp, theme):
        button = _key()
        button.setStyleSheet(render_stylesheet(BUNDLED[theme]))
        button.show()
        _enter(button)
        qapp.processEvents()

        plain = button.grab().toImage()
        play_button = button._run_button.geometry()
        corner = plain.pixelColor(play_button.left() + 2, play_button.center().y())
        key_bg = plain.pixelColor(button.width() // 2, 6)

        assert_that(corner.getRgb()).described_as("play_button disc differs from the key face").is_not_equal_to(
            key_bg.getRgb()
        )


class TestKeyboardAccessToEdit:  # pylint: disable=protected-access,unused-argument
    @pytest.mark.parametrize("key", [Qt.Key.Key_F2, Qt.Key.Key_Menu])
    def test_edit_keys_emit_edit_clicked_once_and_do_not_run(self, qapp, key):
        button = _key(6)
        edits: list[int] = []
        runs: list[int] = []
        button.edit_clicked.connect(edits.append)
        button.run_clicked.connect(runs.append)

        QTest.keyClick(button, key)  # type: ignore[call-overload]

        assert_that(edits).is_equal_to([6])
        assert_that(runs).is_empty()

    def test_space_selects_the_key(self, qapp):
        button = _key(6)
        edits: list[int] = []
        runs: list[int] = []
        button.edit_clicked.connect(edits.append)
        button.run_clicked.connect(runs.append)

        QTest.keyClick(button, Qt.Key.Key_Space)  # type: ignore[call-overload]

        assert_that(edits).is_equal_to([6])
        assert_that(runs).is_empty()

    def test_focus_shows_the_play_button_so_keyboard_users_can_see_the_affordance(self, qapp):
        button = _key()
        button.show()

        QApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        assert_that(button._run_button.isVisible()).is_true()
        QApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
        assert_that(button._run_button.isVisible()).is_false()

    def test_losing_focus_keeps_the_play_button_while_the_pointer_is_still_on_the_key(self, qapp):
        button = _key()
        button.show()
        _enter(button)
        QApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
        button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)

        QApplication.sendEvent(button, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))

        assert_that(button._run_button.isVisible()).is_true()


class TestPlayButtonIcon:  # pylint: disable=protected-access,unused-argument
    def _ink(self, play_button) -> list[tuple[int, int, int]]:
        image = play_button.icon().pixmap(14, 14).toImage()
        pixels = []
        for y in range(image.height()):
            for x in range(image.width()):
                colour = image.pixelColor(x, y)
                if colour.alpha() > 200:
                    pixels.append((colour.red(), colour.green(), colour.blue()))
        return pixels

    def test_the_shipped_svg_is_the_play_circle_icon(self, qapp):
        assert_that(button_grid_module._PLAY_ICON.name).is_equal_to("play-circle.svg")
        assert_that(button_grid_module._PLAY_ICON.is_file()).is_true()
        assert_that(button_grid_module._PLAY_ICON.read_bytes()).contains(b"<svg")

    def test_play_button_drawing_is_21_px_inside_its_30_px_button(self, qapp):
        play_button = _key()._run_button

        assert_that((play_button.iconSize().width(), play_button.iconSize().height())).is_equal_to((21, 21))
        assert_that((play_button.width(), play_button.height())).is_equal_to((30, 30))

    def test_play_button_uses_the_svg_not_a_glyph(self, qapp):
        play_button = _key()._run_button

        assert_that(play_button.icon().isNull()).is_false()
        assert_that(play_button.text()).is_equal_to("")

    def test_play_button_icon_is_filled_with_the_palette_text_colour(self, qapp):
        button = _key()
        palette = QPalette(button.palette())
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#00ff00"))
        button.setPalette(palette)

        ink = self._ink(button._run_button)

        assert_that(ink).is_not_empty()
        assert_that(set(ink)).is_equal_to({(0, 255, 0)})

    def test_play_button_icon_follows_a_palette_change(self, qapp):
        button = _key()
        for colour, expected in (("#ff0000", (255, 0, 0)), ("#0000ff", (0, 0, 255))):
            palette = QPalette(button.palette())
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(colour))
            button.setPalette(palette)

            assert_that(set(self._ink(button._run_button))).described_as(colour).is_equal_to({expected})

    def test_missing_svg_falls_back_to_the_glyph(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(button_grid_module, "_PLAY_ICON", tmp_path / "nope.svg")

        play_button = _key()._run_button

        assert_that(play_button.text()).is_equal_to("▶")
        assert_that(play_button.icon().isNull()).is_true()

    def test_unreadable_svg_falls_back_to_the_glyph(self, qapp, monkeypatch, tmp_path):
        broken = tmp_path / "edit.svg"
        broken.write_bytes(b"this is not an svg")
        monkeypatch.setattr(button_grid_module, "_PLAY_ICON", broken)

        play_button = _key()._run_button

        assert_that(play_button.text()).is_equal_to("▶")

    def test_palette_change_after_a_fallback_does_not_crash(self, qapp, monkeypatch, tmp_path):
        monkeypatch.setattr(button_grid_module, "_PLAY_ICON", tmp_path / "nope.svg")
        button = _key()

        palette = QPalette(button.palette())
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ff0000"))
        button.setPalette(palette)

        assert_that(button._run_button.text()).is_equal_to("▶")

    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_the_svg_play_button_still_fits_its_box_under_the_bundled_themes(self, qapp, theme):
        button = _key()
        button.setStyleSheet(render_stylesheet(BUNDLED[theme]))
        button.show()
        qapp.processEvents()

        hint = button._run_button.sizeHint()

        assert_that(hint.width()).is_less_than_or_equal_to(30)
        assert_that(hint.height()).is_less_than_or_equal_to(30)


class TestSelectedKey:
    def _selected(self, grid: ButtonGridWidget) -> list[int]:
        buttons = grid._buttons  # pylint: disable=protected-access
        return [i for i, b in buttons.items() if b.property("selected") is True]

    def test_set_selected_marks_only_that_key(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))

        grid.set_selected(2)
        assert_that(self._selected(grid)).is_equal_to([2])
        grid.set_selected(4)
        assert_that(self._selected(grid)).is_equal_to([4])

    def test_none_clears_the_selection(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.set_selected(2)

        grid.set_selected(None)

        assert_that(self._selected(grid)).is_empty()

    def test_unknown_index_selects_nothing(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(3))
        grid.set_selected(1)

        grid.set_selected(99)

        assert_that(self._selected(grid)).is_empty()

    def test_rebuilding_the_grid_clears_the_selection(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        grid.set_selected(2)

        grid.build(_make_keys(6))

        assert_that(self._selected(grid)).is_empty()

    def test_theme_outlines_the_selected_key(self, qapp):  # pylint: disable=unused-argument
        stylesheet = render_stylesheet(next(iter(BUNDLED.values())))
        assert_that(stylesheet).contains('KeyButtonWidget[selected="true"]')
