"""Server module."""

import logging
import threading
import time

import rpyc


class Server(rpyc.Service):
    """Main server thread implementing an RPC server that self-terminates after 15 seconds."""

    def on_connect(self, conn):
        """Called when a connection is established."""
        logging.info("Connection established")

    def on_disconnect(self, conn):
        """Called when a connection is closed."""
        logging.info("Connection closed")

    def exposed_get_answer(self):
        """Return the answer to the ultimate question of life, the universe, and everything."""
        return 42

    def exposed_get_question(self):
        """Return the ultimate question of life, the universe, and everything."""
        return "What do you get when you multiply six by nine?"

    def start(self):
        """Start the server."""
        self._thread = threading.Thread(target=self._start_server)
        self._thread.start()

    def stop(self):
        """Stop the server."""
        self._thread.join(timeout=15)

    def _start_server(self):
        """Start the server in a new thread."""
        from rpyc.utils.server import ThreadedServer

        server = ThreadedServer(self, port=18861)
        server.start()
