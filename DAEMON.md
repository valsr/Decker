# Decker server monitor

> Earlier versions of this document described a `--daemon` mode (`python -m decker --daemon`, a `DaemonManager`, and
> client commands such as `start`). None of that exists any more. The server has no `--daemon` option and no `start`
> RPC. Its supervision is done by the **server monitor**, which `poe server` (`python -m decker`) always starts. This
> file keeps its old name so existing links still work.

## What runs

`poe server` launches the **server monitor**, which spawns the **server** as a child process and supervises it. The
server runs headlessly: it talks to the Stream Deck hardware and serves RPyC on `server.host`:`server.port` (default
`localhost:18861`). Clients (the GUI, `poe cli`) connect to that port. The server is already running when a client
connects, which is why there is no `start` RPC.

## What the monitor does

Every `server.health_check_interval` seconds (default 5) it runs one round of checks:

1. **Process alive.** If the child has exited with **code 0** (the `stop` RPC does that) the shutdown was intentional:
   the monitor exits cleanly and does not restart it. Any other exit is a crash and the server is restarted.
2. **Heartbeat.** It calls the server's `heartbeat` RPC. A missing or unhealthy answer counts as a failure; a good
   answer resets the counter. After `server.max_failed_heartbeats` (default 2) consecutive failures the server is
   restarted.
3. **Memory.** It reads the server's resident memory with `psutil` (`decker.common.processes.rss_bytes`). Above
   `server.memory_limit` (default 1 GiB) the server is restarted. An unreadable value is treated as unknown, never as
   over the limit.

A restart stops the child, resets the failure counter and starts a new child. Stopping the child (for a restart or
when the monitor itself stops) asks the server to shut down through a shared event, waits `server.stop_timeout`
seconds for it to exit on its own, then terminates it and, if that fails, kills it. If starting fails it is retried on
the next round. There is no backoff and no maximum restart count today.

The server itself has no self-healing logic; fault tolerance is entirely the monitor's job.

## Settings

All under `server:` in `~/.decker/config.yaml` (defaults in `src/decker/common/config/defaults.yml`):

| Key | Default | Meaning |
|-----|---------|---------|
| `host` | `localhost` | Interface the RPyC server listens on. There is no authentication; keep it on localhost unless remote clients are needed |
| `port` | `18861` | RPyC port |
| `startup_wait` | `5.0` | Seconds the monitor waits after spawning the server to see that its process stays alive |
| `health_check_interval` | `5.0` | Seconds between monitor rounds |
| `max_failed_heartbeats` | `2` | Consecutive failed heartbeats before a restart |
| `memory_limit` | `1073741824` | Server memory limit in bytes |
| `stop_timeout` | `10.0` | Seconds the monitor waits for the server to shut down after being asked to, before it terminates (then kills) the process |
| `device_watch_interval` | `2.0` | How often the server checks its decks are still present |
| `allow_remote_plugin_install` | `false` | Whether non-local clients may install or uninstall plugins |

## Command line

`python -m decker` (or `poe server`) accepts:

| Option | Meaning |
|--------|---------|
| `-v`, `--verbose` | More logging: once for INFO, twice for DEBUG (the default is WARNING) |
| `--prefix DIR` | Locate the `.decker` folder under `DIR` instead of the user's home directory |
| `--device ID_OR_PATH` | Device ID or USB path to use; the server fails to start if the device is not found |
| `--reset-device-data` | Clear persisted key images and labels before starting (for the target device if `--device` is set) |
| `--version` | Print the version |

Everything else is set in the configuration file above.

## Controlling it

```bash
poe server          # start the monitor and the server
poe client          # GUI client
poe cli list        # list the server's RPC commands
poe cli status      # call one
poe cli stop        # stop the server (exit code 0); the monitor then exits too
```

## Platform notes

- Memory is read with `psutil`, so the limit works on Linux, macOS and Windows.
- The monitor stops the server in three steps on every OS: it sets a stop event that the server's watcher thread turns
  into the same shutdown the SIGTERM handler performs (RPyC server closed, managers destroyed, plugins stopped), waits
  `server.stop_timeout` seconds, then calls `terminate()` (SIGTERM on POSIX, `TerminateProcess` on Windows) and finally
  `kill()`. A server that shuts down on request exits with code 0.
- The terminate and kill fallbacks are hard kills on Windows, so the graceful plugin shutdown does not run in that
  case. Each Windows plugin process lives in a kill-on-close Job Object, so helpers of executable
  plugins are still killed there, and also when the server itself is hard-killed (a helper spawned before the process
  is assigned to its job could escape; if a job cannot be created only the psutil process walk is used). See [platform support](docs/platform-support.md).
