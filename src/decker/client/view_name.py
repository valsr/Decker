"""Identifiers for all registered client views."""

from enum import StrEnum


class ViewName(StrEnum):
    """Every view registered in MainWindow's QStackedWidget."""

    CONNECTING = "connecting"
    DASHBOARD = "dashboard"
    DEVICE = "device"
    ERROR = "error"
