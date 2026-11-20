"""Shared fixtures for client tests — a session-wide offscreen QApplication."""

import os

import pytest
from PyQt6.QtWidgets import QApplication

from decker.client.fonts import register_bundled_fonts

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    """A single QApplication instance shared across all client tests."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication([])
    register_bundled_fonts()  # 'DejaVu Sans' is the default font; not every OS ships it
    return app


@pytest.fixture(autouse=True)
def _isolated_icon_cache(tmp_path_factory, monkeypatch):
    """Point the process-wide icon thumbnail cache at a temp directory so no test writes under the real ~/.decker."""
    import decker.client.icon_cache as icon_cache_module  # pylint: disable=import-outside-toplevel

    root = tmp_path_factory.mktemp("icon-cache")
    monkeypatch.setattr(icon_cache_module, "_INSTANCE", icon_cache_module.IconThumbnailCache(root))


@pytest.fixture(autouse=True)
def _inline_preview_jobs(monkeypatch):
    """Run key-preview requests inline so tests need no event loop; threaded behaviour has its own tests."""
    from decker.client.widgets import (
        card_config_panel,  # pylint: disable=import-outside-toplevel
    )

    monkeypatch.setattr(card_config_panel, "_run_in_thread", lambda job, done: done(card_config_panel._run_job(job)))
