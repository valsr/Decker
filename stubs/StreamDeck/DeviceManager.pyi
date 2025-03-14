from _typeshed import Incomplete

from .Devices.StreamDeckMini import StreamDeckMini as StreamDeckMini
from .Devices.StreamDeckNeo import StreamDeckNeo as StreamDeckNeo
from .Devices.StreamDeckOriginal import StreamDeckOriginal as StreamDeckOriginal
from .Devices.StreamDeckOriginalV2 import StreamDeckOriginalV2 as StreamDeckOriginalV2
from .Devices.StreamDeckPedal import StreamDeckPedal as StreamDeckPedal
from .Devices.StreamDeckPlus import StreamDeckPlus as StreamDeckPlus
from .Devices.StreamDeckXL import StreamDeckXL as StreamDeckXL
from .ProductIDs import USBProductIDs as USBProductIDs
from .ProductIDs import USBVendorIDs as USBVendorIDs
from .Transport.Dummy import Dummy as Dummy
from .Transport.LibUSBHIDAPI import LibUSBHIDAPI as LibUSBHIDAPI

class ProbeError(Exception): ...

class DeviceManager:
    USB_VID_ELGATO: int
    USB_PID_STREAMDECK_ORIGINAL: int
    USB_PID_STREAMDECK_ORIGINAL_V2: int
    USB_PID_STREAMDECK_MINI: int
    USB_PID_STREAMDECK_NEO: int
    USB_PID_STREAMDECK_XL: int
    USB_PID_STREAMDECK_MK2: int
    USB_PID_STREAMDECK_PEDAL: int
    USB_PID_STREAMDECK_PLUS: int
    transport: Incomplete
    def __init__(self, transport: Incomplete | None = None) -> None: ...
    def enumerate(self): ...
