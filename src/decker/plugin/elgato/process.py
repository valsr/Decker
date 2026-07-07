"""Node.js subprocess lifecycle for one Elgato-compatible plugin."""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ElgatoPluginProcessError(Exception):
    """The Node.js subprocess for an Elgato plugin could not be started."""


@dataclass(frozen=True)
class ElgatoProcessConfig:
    """Everything needed to spawn one Elgato plugin's Node.js subprocess."""

    plugin_dir: Path
    entry_point: str
    port: int
    plugin_uuid: str
    node_path: str = "node"


class ElgatoPluginProcess:
    """Spawns and tears down the Node.js subprocess backing one Elgato plugin.

    Started when the plugin's first action instance appears on a key, stopped when
    the last one disappears.
    """

    def __init__(self, config: ElgatoProcessConfig) -> None:
        self._config = config
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        """Spawn the Node.js subprocess. Raises ElgatoPluginProcessError if Node is unavailable."""
        if self.is_running:
            return
        cfg = self._config
        try:
            self._process = subprocess.Popen(  # pylint: disable=consider-using-with
                [cfg.node_path, cfg.entry_point, "-port", str(cfg.port), "-pluginUUID", cfg.plugin_uuid],
                cwd=cfg.plugin_dir,
            )
        except FileNotFoundError as exc:
            raise ElgatoPluginProcessError(
                f"Node.js executable {cfg.node_path!r} not found — required to activate {cfg.plugin_uuid}"
            ) from exc
        logging.info("Started Elgato plugin process %s (pid %d)", cfg.plugin_uuid, self._process.pid)

    def stop(self) -> None:
        """Terminate the subprocess, if running."""
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        logging.info("Stopped Elgato plugin process %s", self._config.plugin_uuid)
        self._process = None

    @property
    def is_running(self) -> bool:
        """True while the subprocess is alive."""
        return self._process is not None and self._process.poll() is None
