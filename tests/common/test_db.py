from assertpy import assert_that

from decker.common import db


class TestMigrateLegacyDb:
    def test_renames_legacy_db_when_present(self, tmp_path, monkeypatch):
        legacy = tmp_path / "plugins.db"
        legacy.write_text("legacy data")
        target = tmp_path / "decker.db"
        monkeypatch.setattr(db, "_LEGACY_DB_PATH", legacy)
        monkeypatch.setattr(db, "DB_PATH", target)

        db.migrate_legacy_db()

        assert_that(target.exists()).is_true()
        assert_that(target.read_text()).is_equal_to("legacy data")
        assert_that(legacy.exists()).is_false()

    def test_noop_when_no_legacy_db(self, tmp_path, monkeypatch):
        legacy = tmp_path / "plugins.db"
        target = tmp_path / "decker.db"
        monkeypatch.setattr(db, "_LEGACY_DB_PATH", legacy)
        monkeypatch.setattr(db, "DB_PATH", target)

        db.migrate_legacy_db()  # should not raise

        assert_that(target.exists()).is_false()

    def test_noop_when_target_already_exists(self, tmp_path, monkeypatch):
        legacy = tmp_path / "plugins.db"
        legacy.write_text("legacy data")
        target = tmp_path / "decker.db"
        target.write_text("current data")
        monkeypatch.setattr(db, "_LEGACY_DB_PATH", legacy)
        monkeypatch.setattr(db, "DB_PATH", target)

        db.migrate_legacy_db()

        assert_that(target.read_text()).is_equal_to("current data")
        assert_that(legacy.exists()).is_true()
