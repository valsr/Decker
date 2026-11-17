"""Central prefix configuration for all ~/.decker filesystem paths.

Call configure() once at startup (before any path is consumed) to redirect
every store, config file, and asset directory to a different location.
"""

from pathlib import Path

_prefix: Path = Path.home()


def configure(prefix: Path) -> None:
    """Override the prefix used for all .decker paths.

    Must be called before any path-dependent module is initialised.
    Also reconfigures the config singleton to use the new location.
    """
    global _prefix
    _prefix = prefix
    # Lazy import to avoid circular dependencies at module load time.
    from decker.common import (
        config as _config_module,  # pylint: disable=import-outside-toplevel
    )

    _config_module.configure_prefix(home() / "config.yaml")


def home() -> Path:
    """Return the .decker directory: <prefix>/.decker."""
    return _prefix / ".decker"


def db() -> Path:
    """Return the path to decker.db."""
    return home() / "decker.db"


def client_db() -> Path:
    """Return the path to config.db (client UI state)."""
    return home() / "config.db"


def config_yaml() -> Path:
    """Return the path to config.yaml."""
    return home() / "config.yaml"


def plugins() -> Path:
    """Return the user plugins directory."""
    return home() / "plugins"


def repositories() -> Path:
    """Return the plugin repository cache directory."""
    return home() / "repositories"


def sdk() -> Path:
    """Return the staged plugin SDK root directory."""
    return home() / "sdk"


def assets() -> Path:
    """Return the assets root directory."""
    return home() / "assets"


def user_icons() -> Path:
    """Return the user-uploaded icons directory."""
    return assets() / "user-icons"
