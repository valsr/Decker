"""Configuration command."""

import logging

from decker_server import config, theme


def list_config(keywords=None):
    """List application configuration, optionally filtering by keywords.

    Args:
        keywords: A list of keywords to filter configuration keys by.
    """
    # Filter and display the configuration
    if keywords:
        keywords = [keyword.lower() for keyword in keywords]

    logging.debug("Listing configuration items with keywords: %s", keywords)

    def filter_by_keywords(key: str, _) -> bool:
        if keywords:
            return all(keyword in key for keyword in keywords)
        return True

    config_items = list(config.find(filter_by_keywords))

    if not config_items:
        logging.warning(theme.warning("No configuration items match the specified keywords."))
        return

    logging.debug("Found %d configuration items", len(config_items))
    config_items.sort(key=lambda x: x[0])

    print("Application Configuration:")
    for key, value in config_items:
        print(f"{key}: {config.decode_value(value)}")


def get_config(key):
    """Get a specific configuration value.

    Args:
        key: The configuration key to retrieve.
    """
    logging.debug("Getting configuration item: %s", key)

    if not config.has(key):
        logging.error(theme.error(f"Error: Configuration '{key}' does not exist."))
        return

    value = config.get(key)
    print(f"{key}: {config.decode_value(value)}")


def remove_config(key):
    """Remove a specific configuration value.

    Args:
        key: The configuration key to remove.
    """
    if not config.has(key):
        logging.warning(theme.warning(f"Warning: Configuration '{key}' does not exist."))
        return

    config.unset(key)
    logging.info("Removed configuration: %s", key)


def set_config(key, value):
    """Set a specific configuration value.

    Args:
        key: The configuration key to set.
        value: The value to set for the configuration key.
    """
    if config.has(key):
        old_value = config.get(key)
        logging.warning("Replacing existing configuration '%s': %s -> %s", key, config.decode_value(old_value), value)

    config.set(key, value)
    logging.debug("Set configuration item: %s to %s", key, value)
