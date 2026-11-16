from pathlib import Path

import pytest

import decker.common.paths as paths


@pytest.fixture(autouse=True)
def _reset_prefix():
    original = paths._prefix
    yield
    paths._prefix = original


class TestConfigure:
    def test_configure_changes_home(self, tmp_path):
        paths.configure(tmp_path)
        assert paths.home() == tmp_path / ".decker"

    def test_configure_changes_all_paths(self, tmp_path):
        paths.configure(tmp_path)
        assert paths.db() == tmp_path / ".decker" / "decker.db"
        assert paths.client_db() == tmp_path / ".decker" / "config.db"
        assert paths.config_yaml() == tmp_path / ".decker" / "config.yaml"
        assert paths.plugins() == tmp_path / ".decker" / "plugins"
        assert paths.assets() == tmp_path / ".decker" / "assets"
        assert paths.user_icons() == tmp_path / ".decker" / "assets" / "user-icons"

    def test_default_prefix_is_home(self):
        paths._prefix = Path.home()
        assert paths.home() == Path.home() / ".decker"
