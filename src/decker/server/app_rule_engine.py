"""Switches each connected device's profile and page when the focused window matches an app rule."""

import logging
import threading
from typing import TYPE_CHECKING

from decker.common.manager import Manager
from decker.common.model import RuleTarget, WindowInfo
from decker.common.window_match import resolve_target

if TYPE_CHECKING:
    from decker.server.server_context import ServerContext

_LOGGER = logging.getLogger(__name__)


class AppRuleEngine(Manager):
    """Applies a device's resolved rule target once per change; it never raises out of its entry points."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window: WindowInfo | None = None
        self._last_target: dict[str, RuleTarget | None] = {}
        self._context: "ServerContext | None" = None

    def create(self, context: "ServerContext") -> None:
        """Bind the server context."""
        self._context = context

    def destroy(self) -> None:
        """Forget the window and every device's state."""
        with self._lock:
            self._window = None
            self._last_target.clear()

    @property
    def _ctx(self) -> "ServerContext":
        assert self._context is not None, "AppRuleEngine.create() must be called before use"
        return self._context

    def on_focus(self, window: WindowInfo) -> None:
        """Remember the window and evaluate every connected device against it."""
        with self._lock:
            self._window = window
        for info in self._ctx.device_manager.list_devices():
            if info.id is not None:
                self._evaluate(info.id, window)

    def evaluate_device(self, device_id: str) -> None:
        """Evaluate one device against the last focused window (no-op before the first one)."""
        with self._lock:
            window = self._window
        if window is not None:
            self._evaluate(device_id, window)

    def forget_device(self, device_id: str) -> None:
        """Drop the device's remembered target so its next evaluation applies afresh."""
        with self._lock:
            self._last_target.pop(device_id, None)

    def _evaluate(self, device_id: str, window: WindowInfo) -> None:
        try:
            store = self._ctx.app_rule_store
            if store is None:
                return
            target = resolve_target(store.list_rules(device_id), window)
            with self._lock:
                previous = self._last_target.get(device_id)
                self._last_target[device_id] = target
            if target is not None and target != previous:
                self._apply(device_id, target)
        except Exception:  # pylint: disable=broad-exception-caught
            _LOGGER.exception("AppRuleEngine: evaluating device %s failed", device_id)

    def _apply(self, device_id: str, target: RuleTarget) -> None:
        controller = self._ctx.page_controller
        pages = controller.device_pages(device_id, target.profile_id)
        if pages is None:
            _LOGGER.debug("AppRuleEngine: profile %s of device %s no longer exists", target.profile_id, device_id)
            return
        if controller.active_profile_id(device_id) == target.profile_id and target.page_id in (
            "",
            controller.active_page_id(device_id),
        ):
            return
        if target.page_id and any(page.page_id == target.page_id for page in pages.pages):
            controller.activate(device_id, target.page_id)
        elif controller.active_profile_id(device_id) != target.profile_id:
            controller.activate_profile(device_id, target.profile_id)
