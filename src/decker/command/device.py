"""Command to handle device related operations."""

import logging

from decker import common, hardware
from decker import logging as log


def list_devices():
    """List all devices."""
    logging.debug("Listing all devices")

    # Define headers based on log level
    headers = ["Id", "Type", "Registered"]
    if log.is_debug() or log.is_info():
        headers.extend(["Vendor Id", "Product Id", "Path"])

    # Collect all data for column width calculation
    rows = []
    for device in hardware.list_devices():
        internal_id = device.get_id()
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
