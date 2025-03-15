"""Module interfacing with the StreamDeck hardware."""

from __future__ import annotations

import xxhash
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck


def list_devices() -> list[Device]:
    """
    Enumerate and return a list of all available hardware devices.
    This function uses the DeviceManager to discover connected devices and wraps each result in a Device object.

    Returns:
        list[Device]: A list of Device objects representing all available hardware devices.
    """

    return [Device(x) for x in DeviceManager().enumerate()]


def autoopen(func):
    """Decorator that ensures the device is open before running the function and closes it after if needed."""

    def wrapper(self, *args, **kwargs):
        close_device = False
        try:
            if not self.deck.is_open():
                self.deck.open()
                close_device = True
            return func(self, *args, **kwargs)
        finally:
            if close_device:
                self.deck.close()

    return wrapper


def make_id(text: str | None) -> str | None:
    """
    Generates a unique identifier from the given text using xxhash and custom base60 encoding.

    This function creates a deterministic ID by hashing the input text with xxhash.xxh32
    and converting the resulting integer digest into a custom base60 encoding that avoids
    look-alike characters (such as 'O' vs '0', 'l' vs '1', etc.).

    Args:
        text (str | None): The input text to generate an ID from.

    Returns:
        str | None: A unique string ID derived from the input text, or None if the input is empty.
    """
    if not text:
        return None

    hasher = xxhash.xxh32()
    hasher.update(text)
    digest = hasher.intdigest()

    # convert to a custom base60 encoding (0-9A-Za-z_.-)
    # Define cipher without look-alike characters ( vs /O, 1 vs l, etc.)
    cipher = "0123456789ABCDEFGHIJKLMNPQRSTUVWXYZabcdefghjkmnpqrtuvwxyz_.-"
    base = len(cipher)
    result = ""
    while digest > 0:
        result = cipher[digest % base] + result
        digest //= base
    return result


class Device:
    """
    This class provides a convenient interface for interacting with StreamDeck devices by automatically
    handling the opening and closing of the device connection when necessary.
    """

    def __init__(self, deck: StreamDeck):
        """
        Initialize a hardware handler with a StreamDeck.

        Args:
            deck (StreamDeck): The StreamDeck device to control.
        """
        self.deck = deck
        self._id : str|None = None

    def get_id(self) -> str | None:
        """
        Generate a unique ID for this hardware device.

        Returns:
            str | None: A unique identifier string for the device, or None unable to generate an ID.
        """
        if not self._id:
            self._id = make_id(self.get_serial_number())
        return self._id

    def __getattr__(self, name):
        """
        Forward attribute accesses to the underlying deck.

        This allows us to call methods on the deck directly through the Device instance,
        while still ensuring the device is open before and closed after if needed.
        """
        attr = getattr(self.deck, name)

        if not callable(attr):
            # If the attribute is not a method, return it directly
            return attr

        # Don't wrap methonds that don't need to be opened and closed
        if name not in ["get_serial_number", "get_firmware_version"]:
            return attr

        # wrap to auto-open and close the device
        def wrapper(*args, **kwargs):
            # TODO: Add retry logic here in case of `TransportError("No HID device.")` when needed
            close_device = False
            try:
                if not self.deck.is_open():
                    self.deck.open()
                    close_device = True
                return attr(*args, **kwargs)
            finally:
                if close_device:
                    self.deck.close()

        return wrapper
