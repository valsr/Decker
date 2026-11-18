# Limits, lifecycle and the launch environment

## Package and data limits

| Limit | Value |
|-------|-------|
| Package file size | 64 MiB |
| Uncompressed size | 256 MiB (checked from the headers and again while streaming) |
| Entries in the archive | 10 000 |
| `manifest.json` size | 1 MiB |
| Protocol line size | 8 MiB; longer lines are discarded |
| stderr | read in 8 KiB chunks and logged; never buffered unbounded |
| Raster image from `set_image` | at most 4096 x 4096 pixels |
| Icon file (pack icon or action `icon`) | at most 4 MiB; larger files are ignored |

## Process lifecycle

- A plugin process starts when its first key appears and stops about 10 s after its last key disappears (so
  flipping pages does not respawn it). On stop it gets `shutdown`, then SIGTERM after 3 s, then SIGKILL.
- Each plugin runs in its own process group; stopping or killing it also stops helper processes it started.
- **Crashes**: restart with backoff (0.5 s, 2 s, 5 s). Three crashes within 60 s mark the plugin failed: its keys
  are cleared and labelled "Plugin failed", and clients are notified. Re-saving a key's settings retries it; so
  does a server restart.
- **Hangs**: the server pings every 5 s; no `pong` within 10 s kills the process. A process that sends no `ready`
  within 10 s is killed too.
- **Memory**: the server samples each plugin's resident set size and kills it above the limit, default 256 MiB
  (config key `plugin.memory_limit`, bytes).
- **Flood**: more than 100 messages per second sustained (burst 200) are dropped; staying over budget for 5 s
  continuously kills the plugin (counted as a crash).
- Installing an id that is already installed replaces it; live keys are stopped and re-appear with the new version.
  A failed upgrade restores the previous version.

## Launch environment

The plugin is started with its folder as the working directory and only these variables:

| Variable | Value |
|----------|-------|
| `PATH` | the server's `PATH` |
| `HOME` | the server's `HOME` |
| `LANG` | the server's `LANG` (default `C.UTF-8`) |
| `PYTHONUNBUFFERED` | `1` |
| `PYTHONPATH` | the directory holding the staged SDK (installed Python plugins only) |

Nothing else from the server's environment is passed on. In particular `DISPLAY`, `WAYLAND_DISPLAY`,
`XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` are absent, so desktop-session integrations will not work out of the
box (see the known limitations in the [overview](README.md)).

## Trust model

Plugins and their dependency builds run as your user; there is no sandbox in v1. The only user-facing safeguard on
plugin actions is the confirmation shown before an `open_url` request opens a link.
