"""Context models."""

import logging
from dataclasses import dataclass


@dataclass
class ServerAppContext:
    """Context for the main server app process, which manages the server subprocess and its monitor."""

    verbosity = logging.WARNING
    log_others = False
