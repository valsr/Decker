"""Decker client GUI — connects to the server and provides a control interface."""

import logging
import tkinter as tk
from tkinter import messagebox
from typing import Any

import rpyc.utils.factory
from rpyc.core.protocol import Connection

import decker.common.logging
from decker.common import config


class ClientApplication:
    """Tkinter GUI client for controlling the Decker server."""

    _POLL_INTERVAL_MS = 3000

    def __init__(self) -> None:
        self._host: str = config.get_as("client.server_host", str)
        self._port: int = config.get_as("client.server_port", int)
        self._conn: Connection | None = None
        self._root = tk.Tk()
        self._status_var = tk.StringVar(value="Disconnected")
        self._app_running_var = tk.StringVar(value="—")
        self._build_ui()

    def run(self) -> None:
        """Start the GUI event loop."""
        self._connect()
        self._root.mainloop()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._root.title("Decker")
        self._root.resizable(False, False)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        frame = tk.Frame(self._root, padx=16, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="Server", font=("", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        tk.Label(frame, text=f"{self._host}:{self._port}", fg="gray").grid(row=0, column=1, sticky=tk.W, padx=8)

        tk.Label(frame, text="Connection:").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        tk.Label(frame, textvariable=self._status_var).grid(row=1, column=1, sticky=tk.W, padx=8, pady=(8, 0))

        tk.Label(frame, text="Application:").grid(row=2, column=0, sticky=tk.W, pady=2)
        tk.Label(frame, textvariable=self._app_running_var).grid(row=2, column=1, sticky=tk.W, padx=8, pady=2)

        btn_frame = tk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky=tk.EW)

        tk.Button(btn_frame, text="Start", width=10, command=self._on_start).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(btn_frame, text="Stop", width=10, command=self._on_stop).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(btn_frame, text="Reconnect", width=10, command=self._connect).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Server communication
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._disconnect()
        try:
            self._conn = rpyc.utils.factory.connect(self._host, self._port)
            self._status_var.set("Connected")
            logging.info("Connected to server at %s:%d", self._host, self._port)
            self._poll_status()
        except Exception as e:
            self._status_var.set("Disconnected")
            logging.warning("Could not connect to server: %s", e)
            self._root.after(self._POLL_INTERVAL_MS, self._connect)

    def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._status_var.set("Disconnected")
        self._app_running_var.set("—")

    def _poll_status(self) -> None:
        if self._conn is None:
            return
        try:
            status: dict[str, Any] = self._conn.root.status()
            running = status.get("application_running", False)
            self._app_running_var.set("Running" if running else "Stopped")
            self._root.after(self._POLL_INTERVAL_MS, self._poll_status)
        except Exception as e:
            logging.warning("Lost connection to server: %s", e)
            self._disconnect()
            self._root.after(self._POLL_INTERVAL_MS, self._connect)

    def _rpc(self, method: str) -> Any:
        if self._conn is None:
            messagebox.showwarning("Not connected", "No connection to the server.")
            return None
        try:
            return getattr(self._conn.root, method)()
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._disconnect()
            return None

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        result = self._rpc("start")
        if result is False:
            messagebox.showinfo("Info", "Application is already running.")

    def _on_stop(self) -> None:
        result = self._rpc("stop")
        if result is False:
            messagebox.showinfo("Info", "Application is not running.")

    def _on_close(self) -> None:
        self._disconnect()
        self._root.destroy()


def main() -> None:
    """Client entry point."""
    decker.common.logging.configure(level=logging.WARNING)
    app = ClientApplication()
    app.run()


if __name__ == "__main__":
    main()
