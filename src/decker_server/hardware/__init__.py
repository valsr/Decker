from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck


def list_devices() -> list[StreamDeck]:
    return DeviceManager().enumerate()

def get_internal_device_id(device: StreamDeck) -> str:
    path = device.id()
    vendor = device.vendor_id()
    product = device.product_id()
    
    return device.id()
