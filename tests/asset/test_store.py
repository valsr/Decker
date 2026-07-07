from assertpy import assert_that

from decker.asset.store import IconPackStore


class TestIconPacks:
    def test_list_empty_initially(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        assert_that(store.list_packs()).is_equal_to([])

    def test_add_then_list_returns_pack(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        store.add_pack("uuid-1", "My Pack", "1.0.0", "/path/to/pack")
        result = store.list_packs()
        assert_that(result).is_equal_to(
            [{"uuid": "uuid-1", "name": "My Pack", "version": "1.0.0", "path": "/path/to/pack"}]
        )

    def test_get_pack_returns_none_when_missing(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        assert_that(store.get_pack("missing")).is_none()

    def test_get_pack_returns_matching_pack(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        store.add_pack("uuid-1", "My Pack", "1.0.0", "/path")
        assert_that(store.get_pack("uuid-1")).is_equal_to(
            {"uuid": "uuid-1", "name": "My Pack", "version": "1.0.0", "path": "/path"}
        )

    def test_add_pack_overwrites_existing_uuid(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        store.add_pack("uuid-1", "Old Name", "1.0.0", "/path")
        store.add_pack("uuid-1", "New Name", "2.0.0", "/new-path")
        pack = store.get_pack("uuid-1")
        assert pack is not None
        assert_that(pack["name"]).is_equal_to("New Name")

    def test_remove_pack(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        store.add_pack("uuid-1", "My Pack", "1.0.0", "/path")
        store.remove_pack("uuid-1")
        assert_that(store.get_pack("uuid-1")).is_none()

    def test_remove_unknown_pack_is_noop(self, tmp_path):
        store = IconPackStore(tmp_path / "decker.db")
        store.remove_pack("missing")  # should not raise


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

    def test_shares_db_file_with_iconpacks_table(self, tmp_path):
        db_path = tmp_path / "decker.db"
        store = IconPackStore(db_path)
        store.add_pack("uuid-1", "Pack", "1.0.0", "/path")
        store.set_user_icon("ctx-1", "/icon.svg")
        reopened = IconPackStore(db_path)
        assert_that(reopened.get_pack("uuid-1")).is_not_none()
        assert_that(reopened.get_user_icon("ctx-1")).is_equal_to("/icon.svg")
