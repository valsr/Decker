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
