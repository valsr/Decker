import sqlite3
from pathlib import Path

from assertpy import assert_that

from decker.common.dbmigrate import rename_column
from decker.plugin.settings_store import PluginSettingsStore
from decker.server.key_assignments import KeyAssignmentStore


def test_rename_column_only_when_the_old_one_exists() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (a TEXT, b TEXT)")

    assert_that(rename_column(db, "t", "a", "c")).is_true()
    assert_that(rename_column(db, "t", "a", "c")).is_false()
    assert_that(rename_column(db, "t", "b", "c")).is_false()  # the target name is taken
    assert_that(rename_column(db, "missing", "a", "c")).is_false()
    assert_that([r[1] for r in db.execute("PRAGMA table_info(t)")]).is_equal_to(["c", "b"])


def test_settings_store_reads_a_database_that_still_has_action_uuid(tmp_path: Path) -> None:
    path = tmp_path / "decker.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE settings (plugin_uuid TEXT NOT NULL, action_uuid TEXT NOT NULL, context_id TEXT NOT NULL, "
        "settings TEXT NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "PRIMARY KEY (plugin_uuid, action_uuid, context_id))"
    )
    db.execute("INSERT INTO settings VALUES ('p', 'p.a', 'c', '{\"x\": 1}', NULL)")
    db.commit()
    db.close()

    store = PluginSettingsStore(path)

    assert_that(store.get_settings("p", "p.a", "c")).is_equal_to({"x": 1})


def test_key_assignments_survive_the_card_uuid_rename(tmp_path: Path) -> None:
    path = tmp_path / "decker.db"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE key_assignments (device_id TEXT NOT NULL, page_id TEXT NOT NULL, key_index INTEGER NOT NULL, "
        "plugin_uuid TEXT NOT NULL, action_uuid TEXT NOT NULL, context_id TEXT NOT NULL, "
        "settings TEXT NOT NULL DEFAULT '{}', appearance TEXT NOT NULL DEFAULT '{}', "
        "PRIMARY KEY (device_id, page_id, key_index))"
    )
    db.execute("INSERT INTO key_assignments VALUES ('d', 'p1', 3, 'com.x', 'com.x.y', 'ctx', '{}', '{}')")
    db.commit()
    db.close()
    store = KeyAssignmentStore(db_path=path)
    store.create(None)  # type: ignore[arg-type]
    try:
        found = store.get("d", "p1", 3)
        assert found is not None
        assert_that(found.target.card_uuid).is_equal_to("com.x.y")
    finally:
        store.destroy()
