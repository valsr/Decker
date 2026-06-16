from assertpy import assert_that

from decker.plugin.settings_store import PluginSettingsStore


class TestPluginSettingsStore:
    def test_get_settings_returns_empty_dict_when_unset(self, tmp_path):
        store = PluginSettingsStore(tmp_path / "plugins.db")
        assert_that(store.get_settings("p", "a", "ctx")).is_equal_to({})

    def test_set_then_get_roundtrips(self, tmp_path):
        store = PluginSettingsStore(tmp_path / "plugins.db")
        store.set_settings("p", "a", "ctx", {"foo": "bar", "n": 1})
        assert_that(store.get_settings("p", "a", "ctx")).is_equal_to({"foo": "bar", "n": 1})

    def test_set_settings_overwrites_previous_value(self, tmp_path):
        store = PluginSettingsStore(tmp_path / "plugins.db")
        store.set_settings("p", "a", "ctx", {"v": 1})
        store.set_settings("p", "a", "ctx", {"v": 2})
        assert_that(store.get_settings("p", "a", "ctx")).is_equal_to({"v": 2})

    def test_settings_persist_across_store_instances(self, tmp_path):
        db_path = tmp_path / "plugins.db"
        PluginSettingsStore(db_path).set_settings("p", "a", "ctx", {"v": 1})
        reopened = PluginSettingsStore(db_path)
        assert_that(reopened.get_settings("p", "a", "ctx")).is_equal_to({"v": 1})

    def test_different_contexts_are_independent(self, tmp_path):
        store = PluginSettingsStore(tmp_path / "plugins.db")
        store.set_settings("p", "a", "ctx-1", {"v": 1})
        store.set_settings("p", "a", "ctx-2", {"v": 2})
        assert_that(store.get_settings("p", "a", "ctx-1")).is_equal_to({"v": 1})
        assert_that(store.get_settings("p", "a", "ctx-2")).is_equal_to({"v": 2})

    def test_creates_parent_directory(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "plugins.db"
        PluginSettingsStore(db_path)
        assert_that(db_path.parent.exists()).is_true()
