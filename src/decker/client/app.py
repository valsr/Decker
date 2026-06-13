"""Client utility for interacting with the Decker daemon."""

import argparse
import sys
from typing import Any

import rpyc.utils.factory
from rpyc.core.protocol import Connection


def connect_to_daemon(port: int = 18861) -> Connection | None:
    """
    Connect to the Decker daemon.

    Args:
        port (int): The port where the daemon is running.

    Returns:
        rpyc.Connection | None: The connection object if successful, None otherwise.
    """
    try:
        conn: Connection = rpyc.utils.factory.connect("localhost", port)
        return conn
    except Exception as e:
        print(f"Failed to connect to daemon on port {port}: {e}")
        return None


def get_daemon_status(port: int = 18861) -> dict[str, Any] | None:
    """
    Get the status of the Decker daemon.

    Args:
        port (int): The port where the daemon is running.

    Returns:
        dict[str, Any] | None: Status information if successful, None otherwise.
    """
    conn: Connection | None = connect_to_daemon(port)
    if conn is None:
        return None

    try:
        status = conn.root.status()
        conn.close()
        return status
    except Exception as e:
        print(f"Failed to get daemon status: {e}")
        return None


def send_heartbeat(port: int = 18861) -> dict[str, Any] | None:
    """
    Send a heartbeat to the Decker daemon.

    Args:
        port (int): The port where the daemon is running.

    Returns:
        dict[str, Any] | None: Heartbeat response if successful, None otherwise.
    """
    conn = connect_to_daemon(port)
    if conn is None:
        return None

    try:
        response = conn.root.heartbeat()
        conn.close()
        return response
    except Exception as e:
        print(f"Failed to send heartbeat: {e}")
        return None


def start_application(port: int = 18861) -> bool:
    """
    Start the application via the daemon.

    Args:
        port (int): The port where the daemon is running.

    Returns:
        bool: True if successful, False otherwise.
    """
    conn = connect_to_daemon(port)
    if conn is None:
        return False

    try:
        result = conn.root.start_application()
        conn.close()
        return result
    except Exception as e:
        print(f"Failed to start application: {e}")
        return False


def stop_application(port: int = 18861) -> bool:
    """
    Stop the application via the daemon.

    Args:
        port (int): The port where the daemon is running.

    Returns:
        bool: True if successful, False otherwise.
    """
    conn = connect_to_daemon(port)
    if conn is None:
        return False

    try:
        result = conn.root.stop_application()
        conn.close()
        return result
    except Exception as e:
        print(f"Failed to stop application: {e}")
        return False


def main():
    """Main entry point for the client utility."""
    parser = argparse.ArgumentParser(
        prog="decker-client", description="Client utility for interacting with the Decker daemon"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=18861,
        help="Port where the daemon is running (default: 18861)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("status", help="Get daemon status")
    subparsers.add_parser("heartbeat", help="Send heartbeat to daemon")
    subparsers.add_parser("start", help="Start the application via daemon")
    subparsers.add_parser("stop", help="Stop the application via daemon")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "status":
        status = get_daemon_status(args.port)
        if status:
            print("Daemon Status:")
            for key, value in status.items():
                print(f"  {key}: {value}")
        else:
            print("Failed to get daemon status")
            sys.exit(1)

    elif args.command == "heartbeat":
        response = send_heartbeat(args.port)
        if response:
            print("Heartbeat Response:")
            for key, value in response.items():
                print(f"  {key}: {value}")
        else:
            print("Failed to send heartbeat")
            sys.exit(1)

    elif args.command == "start":
        if start_application(args.port):
            print("Application started successfully")
        else:
            print("Failed to start application")
            sys.exit(1)

    elif args.command == "stop":
        if stop_application(args.port):
            print("Application stopped successfully")
        else:
            print("Failed to stop application")
            sys.exit(1)


if __name__ == "__main__":
    main()
