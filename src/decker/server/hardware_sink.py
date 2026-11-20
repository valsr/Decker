"""Hardware effects of a key face: the sink PluginManager draws through, and writing a composed face to it."""

import logging
from collections.abc import Callable
from typing import Any

from decker.animation.model import AnimationSpec
from decker.plugin.target import CardTarget
from decker.server.appearance import Composed


class StreamDeckHardwareSink:
    """Applies hardware effects via DeviceManager; falls back gracefully if no device is open.

    set_title is deliberately lightweight — it stores the label in the shared label dict
    for client polling instead of rendering text to hardware (the plugin renders its own
    image via set_image).
    """

    def __init__(
        self,
        device_manager: Any,  # DeviceManager | None — avoid circular import at module level
        label_setter: Callable[[str, int, str], None],
    ) -> None:
        self._device_manager = device_manager
        self._label_setter = label_setter

    def set_image(self, device_id: str, key_index: int, image: bytes) -> None:
        """Render image (SVG/PNG/JPEG bytes) on the given device's key."""
        if self._device_manager is not None:
            self._device_manager.set_image_bytes(device_id, key_index, image)
        else:
            logging.debug("set_image: no DeviceManager available")

    def set_animation(self, device_id: str, key_index: int, spec: AnimationSpec) -> None:
        """Animate the key (its poster already written by set_image) and register spec for the key_animation RPC."""
        if self._device_manager is None:
            return
        if self._device_manager.set_animation(device_id, key_index, spec):
            factory = self._device_manager.animation_factory
            if factory is not None:
                factory.register(spec)

    def is_playing(self, device_id: str, key_index: int, animation_id: str) -> bool:
        """Whether the key's open device already plays (or is about to play) the animation animation_id."""
        manager = self._device_manager
        return manager is not None and manager.playing_animation_id(device_id, key_index) == animation_id

    def set_title(self, device_id: str, key_index: int, title: str) -> None:
        """Store the display label for client polling (hardware text not rendered)."""
        self._label_setter(device_id, key_index, title)

    def clear_image(self, device_id: str, key_index: int) -> None:
        """Blank the key and drop its stored image."""
        if self._device_manager is not None:
            device = self._device_manager.open_device(device_id)
            if device is not None:
                device.clear_key_image(key_index)
            self._device_manager.clear_key_state(device_id, key_index)

    def set_state(self, device_id: str, key_index: int, state: int) -> None:
        """No-op: multi-state icon rendering is not implemented yet."""
        logging.debug("set_state(%s, %d, %d): not implemented", device_id, key_index, state)

    def show_alert(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_alert(%s, %d): not implemented", device_id, key_index)

    def show_ok(self, device_id: str, key_index: int) -> None:
        """No-op: indicator rendering is not implemented yet."""
        logging.debug("show_ok(%s, %d): not implemented", device_id, key_index)


def write_face(sink: StreamDeckHardwareSink, target: CardTarget, composed: Composed, poster: bool) -> bool:
    """Write a composed key face and start its animation; return whether the key was touched.

    The animation id covers the whole PNG, so a key already playing it needs neither a poster nor a restart.
    With poster=False the key keeps the image it shows (a cached poster): only an animation is started.
    """
    animation = composed.animation
    if animation is not None and sink.is_playing(target.device_id, target.key_index, animation.animation_id):
        return False
    if poster:
        # Poster first: a static write ends the key's animation, so the animation must start after it.
        sink.set_image(target.device_id, target.key_index, composed.png)
    if animation is not None:
        sink.set_animation(target.device_id, target.key_index, animation)
    return poster or animation is not None
