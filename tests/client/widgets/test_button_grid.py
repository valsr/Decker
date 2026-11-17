import json

from assertpy import assert_that
from PyQt6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QDropEvent, QEnterEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

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

    def test_clicking_key_emits_key_selected(self, qapp):  # pylint: disable=unused-argument
        grid = ButtonGridWidget()
        grid.build(_make_keys(6))
        received: list[int] = []
        grid.key_selected.connect(received.append)

        layout_item = grid._grid_layout.itemAt(2)  # pylint: disable=protected-access
        assert layout_item is not None
        button = layout_item.widget()
        assert isinstance(button, KeyButtonWidget)
        button.click()

        assert_that(received).is_equal_to([2])

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


class TestKeyEditPencil:  # pylint: disable=protected-access,unused-argument
    def test_pencil_is_hidden_until_the_pointer_enters(self, qapp):
        button = _key()
        button.show()

        assert_that(button._edit_button.isVisible()).is_false()

    def test_pencil_shows_on_enter_and_hides_on_leave(self, qapp):
        button = _key()
        button.show()

        _enter(button)
        assert_that(button._edit_button.isVisible()).is_true()
        _leave(button)
        assert_that(button._edit_button.isVisible()).is_false()

    def test_pencil_sits_in_the_top_right_corner(self, qapp):
        button = _key()
        button.show()

        geometry = button._edit_button.geometry()

        assert_that((geometry.width(), geometry.height())).is_equal_to((20, 20))
        assert_that(button.width() - geometry.right() - 1).is_equal_to(4)
        assert_that(geometry.top()).is_equal_to(4)

    def test_pencil_has_a_tooltip_and_something_to_look_at(self, qapp):
        pencil = _key()._edit_button

        assert_that(pencil.toolTip()).is_equal_to("Edit this key")
        assert_that(pencil.icon().isNull() and not pencil.text()).is_false()

    def test_pencil_click_emits_edit_clicked_with_the_index_and_not_clicked(self, qapp):
        button = _key(7)
        edits: list[int] = []
        clicks: list[bool] = []
        button.edit_clicked.connect(edits.append)
        button.clicked.connect(clicks.append)

        button._edit_button.click()

        assert_that(edits).is_equal_to([7])
        assert_that(clicks).is_empty()

    def test_key_click_emits_clicked_and_not_edit_clicked(self, qapp):
        button = _key(7)
        edits: list[int] = []
        clicks: list[bool] = []
        button.edit_clicked.connect(edits.append)
        button.clicked.connect(clicks.append)

        button.click()

        assert_that(clicks).is_length(1)
        assert_that(edits).is_empty()

    def test_pencil_press_does_not_start_the_long_press_timer(self, qapp):
        button = _key()
        button.show()
        _enter(button)
        long_presses: list[int] = []
        button.long_pressed.connect(long_presses.append)

        QTest.mousePress(button._edit_button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]

        assert_that(button._long_press_timer.isActive()).is_false()
        assert_that(long_presses).is_empty()
        QTest.mouseRelease(button._edit_button, Qt.MouseButton.LeftButton)  # type: ignore[call-overload]

    def test_pencil_stays_visible_when_the_pointer_moves_onto_it_and_hides_when_it_leaves(self, qapp):
        button = _key()
        button.move(100, 100)
        button.show()
        qapp.processEvents()

        QTest.mouseMove(button, QPoint(10, 50))  # type: ignore[call-overload]
        qapp.processEvents()
        assert_that(button._edit_button.isVisible()).described_as("after entering the key").is_true()

        QTest.mouseMove(button._edit_button, QPoint(10, 10))  # type: ignore[call-overload]
        qapp.processEvents()
        assert_that(button._edit_button.isVisible()).described_as("pointer now on the pencil").is_true()

        QTest.mouseMove(button, QPoint(10, 50))  # type: ignore[call-overload]
        qapp.processEvents()
        assert_that(button._edit_button.isVisible()).described_as("back on the key body").is_true()

    def test_pencil_does_not_swallow_drops(self, qapp):
        button = _key(4)
        button.show()
        dropped: list[tuple[int, object]] = []
        button.action_dropped.connect(lambda i, d: dropped.append((i, d)))
        mime = QMimeData()
        mime.setData("application/x-decker-action", QByteArray(json.dumps({"plugin_uuid": "p"}).encode()))
        center = QPointF(button._edit_button.geometry().center())

        event = QDropEvent(
            center, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
        button.dropEvent(event)

        assert_that(button._edit_button.acceptDrops()).is_false()  # so Qt hands the drop to the key
        assert_that(dropped).is_equal_to([(4, {"plugin_uuid": "p"})])
