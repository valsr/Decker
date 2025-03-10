import logging

from decker_server import common, hardware, theme, logging as log

def list_devices():
    """List all devices."""
    logging.debug("Listing all devices")

    # Define headers based on log level
    headers = ["ID", "Type", "Registered"]
    if log.is_debug() or log.is_info():
        headers.extend(["Vendor", "Product", "Path"])

    # Collect all data for column width calculation
    rows = []
    for device in hardware.list_devices():
        internal_id = hardware.get_internal_device_id(device)
        registered = "TBD"
        vendor = device.vendor_id()
        product = device.product_id()
        device_id = device.id()

        row = [internal_id, device.DECK_TYPE, registered]
        if log.is_debug() or log.is_info():
            row.extend([vendor, product, device_id])
        rows.append(row)

    # Print devices
    common.column_print(headers, rows)
