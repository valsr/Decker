"""Script that starts Decker server instance."""

if __name__ == "__main__":
    import logging
    from time import sleep

    # configure parser
    logging.basicConfig(level=logging.DEBUG)
    logging.debug("Starting server")
    sleep(120)
    logging.debug("Stopping server")
