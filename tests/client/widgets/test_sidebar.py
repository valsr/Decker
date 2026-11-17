import base64
import json
from pathlib import Path

from assertpy import assert_that
from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtWidgets import QListView, QToolButton, QVBoxLayout

from decker.client.action_icons import action_pixmap
from decker.client.widgets.sidebar import DRAG_ICON_SIZE, ICON_SIZE, SidebarWidget

_ACTIONS = [
    {"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.show", "action_name": "Show Clock"},
    {"plugin_uuid": "p", "plugin_name": "P", "action_uuid": "p.toggle", "action_name": "Toggle Light"},
]


class TestSidebarWidget:
    def test_set_actions_populates_list(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)
        assert_that(sidebar._action_list.count()).is_equal_to(2)  # pylint: disable=protected-access

    def test_search_filters_case_insensitively(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)

        sidebar._search.setText("clock")  # pylint: disable=protected-access

        assert_that(sidebar._action_list.count()).is_equal_to(1)  # pylint: disable=protected-access
        item = sidebar._action_list.item(0)  # pylint: disable=protected-access
        assert item is not None
        assert_that(item.text()).is_equal_to("Show Clock")

    def test_search_with_no_matches_clears_list(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)

        sidebar._search.setText("nonexistent")  # pylint: disable=protected-access

        assert_that(sidebar._action_list.count()).is_equal_to(0)  # pylint: disable=protected-access

    def test_clearing_search_restores_full_list(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions(_ACTIONS)
        sidebar._search.setText("clock")  # pylint: disable=protected-access

        sidebar._search.setText("")  # pylint: disable=protected-access

        assert_that(sidebar._action_list.count()).is_equal_to(2)  # pylint: disable=protected-access

    def test_has_no_buttons_and_list_fills_remaining_space(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        layout = sidebar.layout()
        assert isinstance(layout, QVBoxLayout)

        assert_that(sidebar.findChildren(QToolButton)).is_empty()
        assert_that(layout.stretch(layout.indexOf(sidebar._action_list))).is_equal_to(
            1
        )  # pylint: disable=protected-access


_COUNTER_PNG = Path(__file__).parents[2] / "fixtures" / "plugins" / "com.decker.testfixture" / "icons" / "counter.png"
_COUNTER = {
    "plugin_uuid": "com.decker.testfixture",
    "plugin_name": "Counter",
    "action_uuid": "com.decker.testfixture.counter",
    "action_name": "Counter",
    "icon_b64": base64.b64encode(_COUNTER_PNG.read_bytes()).decode("ascii"),
}


class TestActionGrid:  # pylint: disable=protected-access
    def test_shows_tiles_with_icon_above_name(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        action_list = sidebar._action_list

        assert_that(action_list.viewMode()).is_equal_to(QListView.ViewMode.IconMode)
        assert_that(action_list.isWrapping()).is_true()
        assert_that(action_list.iconSize()).is_equal_to(QSize(ICON_SIZE, ICON_SIZE))

    def test_items_carry_icon_and_tooltip(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions([_COUNTER, _ACTIONS[0]])

        counter = sidebar._action_list.item(0)
        plain = sidebar._action_list.item(1)
        assert counter is not None and plain is not None
        assert_that(counter.icon().isNull()).is_false()
        assert_that(plain.icon().isNull()).is_false()  # generated letter tile
        assert_that(counter.toolTip()).is_equal_to("Counter: Counter")

    def test_counter_tile_uses_counter_image(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions([_COUNTER])
        item = sidebar._action_list.item(0)
        assert item is not None

        shown = item.icon().pixmap(ICON_SIZE, ICON_SIZE).toImage()

        assert_that(shown.pixelColor(ICON_SIZE // 2, 4).name()).is_equal_to(
            action_pixmap(_COUNTER, ICON_SIZE).toImage().pixelColor(ICON_SIZE // 2, 4).name()
        )

    def test_icons_are_reused_across_searches(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions([_COUNTER])
        first = sidebar._icons[("com.decker.testfixture", "com.decker.testfixture.counter")]

        sidebar._search.setText("count")

        assert_that(sidebar._icons[("com.decker.testfixture", "com.decker.testfixture.counter")]).is_same_as(first)


class TestDrag:  # pylint: disable=protected-access
    def test_drag_shows_action_icon_centred_on_cursor(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions([_COUNTER])
        item = sidebar._action_list.item(0)
        assert item is not None

        drag = sidebar._action_list.build_drag(item)

        pixmap = drag.pixmap()
        assert_that(pixmap.toImage()).is_equal_to(action_pixmap(_COUNTER, DRAG_ICON_SIZE).toImage())
        assert_that(drag.hotSpot()).is_equal_to(QPoint(pixmap.width() // 2, pixmap.height() // 2))

    def test_drag_payload_identifies_action_without_icon_bytes(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()
        sidebar.set_actions([_COUNTER])
        item = sidebar._action_list.item(0)
        assert item is not None

        mime = sidebar._action_list.build_drag(item).mimeData()

        assert mime is not None
        payload = json.loads(bytes(mime.data("application/x-decker-action").data()))
        assert_that(payload).is_equal_to(
            {
                "plugin_uuid": "com.decker.testfixture",
                "plugin_name": "Counter",
                "action_uuid": "com.decker.testfixture.counter",
                "action_name": "Counter",
            }
        )

    def test_start_drag_without_current_item_does_nothing(self, qapp):  # pylint: disable=unused-argument
        sidebar = SidebarWidget()

        sidebar._action_list.startDrag(Qt.DropAction.CopyAction)  # should not raise
