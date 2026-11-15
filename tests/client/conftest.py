"""Shared fixtures for client tests — a session-wide offscreen QApplication."""

import os

import pytest
from PyQt6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """A single QApplication instance shared across all client tests."""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    return QApplication([])


@pytest.fixture
def isolated_config(tmp_path):
    """Point the config singleton at a temporary user config file, restoring it afterwards."""
    from decker.common import config  # pylint: disable=import-outside-toplevel

    saved = (config._config, config._USER_CONFIG_PATH)  # pylint: disable=protected-access
    config.configure_prefix(tmp_path / "config.yaml")
    yield config
    config._config, config._USER_CONFIG_PATH = saved  # pylint: disable=protected-access
