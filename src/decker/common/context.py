"""Context models."""

import logging
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerAppContext:
    """Context for the main server app process, which manages the server subprocess and its monitor."""

    verbosity: int = logging.WARNING
    log_others: bool = False
    prefix: Path = field(default_factory=Path.home)
    target_device: str | None = None
    reset_device_data: bool = False
