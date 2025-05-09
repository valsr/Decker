from decker.hardware import Device


class DeckerError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


class DeviceNotFoundError(DeckerError):
    def __init__(self, device_id: str, available_devices: list[Device] | None):
        self.device_id = device_id
        message = f"Device with id {device_id} not found."
        if available_devices:
            device_ids = [d.get_id() or "Unknown" for d in available_devices]
            message += f" Choose one from: {', '.join(device_ids)}"
        else:
            message += " No devices found."
        super().__init__(message)
