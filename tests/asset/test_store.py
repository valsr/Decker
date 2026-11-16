from assertpy import assert_that

from decker.asset.store import IconPackStore


class TestUserIconAssignments:
    def test_get_returns_none_when_unset(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        assert_that(store.get_user_icon("ctx-1")).is_none()

    def test_set_then_get_roundtrips(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        store.set_user_icon("ctx-1", "/path/to/icon.svg")
        assert_that(store.get_user_icon("ctx-1")).is_equal_to("/path/to/icon.svg")

    def test_set_overwrites_previous_assignment(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        store.set_user_icon("ctx-1", "/old.svg")
        store.set_user_icon("ctx-1", "/new.svg")
        assert_that(store.get_user_icon("ctx-1")).is_equal_to("/new.svg")

    def test_assignments_persist_across_connections(self, tmp_path):
        db_path = tmp_path / "decker.db"
        IconPackStore(db_path).set_user_icon("ctx-1", "/icon.svg")
        assert_that(IconPackStore(db_path).get_user_icon("ctx-1")).is_equal_to("/icon.svg")
