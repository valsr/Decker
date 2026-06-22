"""Context models."""

from dataclasses import dataclass
import logging


@dataclass
class ServerAppContext:
    """Context for the main server app process, which manages the server subprocess and its monitor."""
    verbosity =  logging.WARNING
