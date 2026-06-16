"""View base class and manager for the Decker client."""

import logging

from PyQt6.QtWidgets import QStackedWidget, QWidget


class View(QWidget):
    """Base class for all client views. Subclasses override on_show/on_hide for lifecycle events."""

    def on_show(self) -> None:
        """Called when this view becomes the active view."""

    def on_hide(self) -> None:
        """Called when this view is no longer the active view."""


class ViewManager:
    """Manages view navigation and lifecycle callbacks over a QStackedWidget."""

    def __init__(self, stack: QStackedWidget) -> None:
        self._stack = stack
        self._views: dict[str, View] = {}
        self._current: View | None = None

    @property
    def current(self) -> View | None:
        """The currently active view, or None before the first navigation."""
        return self._current

    def register(self, name: str, view: View) -> None:
        """Register a view under a name and add it to the widget stack."""
        self._stack.addWidget(view)
        self._views[name] = view

    def navigate(self, name: str) -> None:
        """Switch to the named view, calling on_hide on the current and on_show on the target.

        No-op if the target is already the current view.
        """
        view = self._views.get(name)
        if view is None:
            raise KeyError(f"Unknown view: {name!r}")
        if self._current is view:
            return
        if self._current is not None:
            self._current.on_hide()
        self._current = view
        self._stack.setCurrentWidget(view)
        view.on_show()
        logging.debug("Navigated to view %r", name)

    def hide_current(self) -> None:
        """Call on_hide on the current view and clear it — use on window close."""
        if self._current is not None:
            self._current.on_hide()
            self._current = None
