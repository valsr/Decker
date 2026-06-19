"""Abstract base class for all client views."""

from abc import ABCMeta, abstractmethod

from PyQt6.QtWidgets import QWidget

from decker.client.events import AppEvent


class _ViewMeta(type(QWidget), ABCMeta):  # type: ignore[misc] # pylint: disable=inconsistent-mro
    """Combines Qt's sip metaclass with ABCMeta so BaseView can declare abstractmethod."""


class BaseView(QWidget, metaclass=_ViewMeta):  # pylint: disable=invalid-metaclass
    """A single screen hosted in MainWindow's QStackedWidget.

    Views are read-only consumers of AppContext — they read it in on_activate()
    but never write to it directly; transitions and state writes go through MainWindow.
    """

    @abstractmethod
    def on_activate(self) -> None:
        """Called when this view becomes the active view."""

    @abstractmethod
    def on_deactivate(self) -> None:
        """Called when this view is no longer the active view."""

    def handle_event(self, event: AppEvent) -> bool | None:
        """Handle an AppEvent forwarded by the EventManager. Return True to stop propagation. No-op by default."""

    def save_state(self) -> None:
        """Persist any view-owned UI state before the window closes. No-op by default."""
