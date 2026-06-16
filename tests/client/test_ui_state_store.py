from assertpy import assert_that

from decker.client.ui_state_store import UiStateStore


class TestUiStateStore:
    def test_get_returns_none_when_unset(self, tmp_path):
        store = UiStateStore(tmp_path / "config.db")
        assert_that(store.get("missing")).is_none()

    def test_set_then_get_roundtrips_dict(self, tmp_path):
        store = UiStateStore(tmp_path / "config.db")
        store.set("window_geometry", {"x": 1, "y": 2, "w": 3, "h": 4})
        assert_that(store.get("window_geometry")).is_equal_to({"x": 1, "y": 2, "w": 3, "h": 4})

    def test_set_then_get_roundtrips_list(self, tmp_path):
        store = UiStateStore(tmp_path / "config.db")
        store.set("splitter_main", [200, 600])
        assert_that(store.get("splitter_main")).is_equal_to([200, 600])

    def test_set_then_get_roundtrips_int(self, tmp_path):
        store = UiStateStore(tmp_path / "config.db")
        store.set("sidebar_collapsed", 0)
        assert_that(store.get("sidebar_collapsed")).is_equal_to(0)

    def test_set_overwrites_previous_value(self, tmp_path):
        store = UiStateStore(tmp_path / "config.db")
        store.set("key", "old")
        store.set("key", "new")
        assert_that(store.get("key")).is_equal_to("new")

    def test_persists_across_store_instances(self, tmp_path):
        db_path = tmp_path / "config.db"
        UiStateStore(db_path).set("key", "value")
        assert_that(UiStateStore(db_path).get("key")).is_equal_to("value")

    def test_creates_parent_directory(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "config.db"
        UiStateStore(db_path)
        assert_that(db_path.parent.exists()).is_true()
