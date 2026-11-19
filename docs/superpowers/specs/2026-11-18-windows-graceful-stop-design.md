# Graceful server stop on Windows — design

Follow-up to `2026-11-18-core-portability-design.md` (PR #42). Small change.

## Intent

When the server monitor restarts or stops the server, the server should shut down gracefully on every OS: close the RPyC server, then destroy its managers (which stops every plugin process, closes stores and releases the devices). Today that only happens on POSIX, because the monitor ends the child with `multiprocessing.Process.terminate()`: SIGTERM on POSIX (the server's handler closes the RPyC server and the `finally` block in `_run_server` destroys the managers), but `TerminateProcess` on Windows, a hard kill that skips all of it. After a Windows hard kill, plugins survive only if their stdin closing makes them exit.

## Goals

- A stop request that works the same on Linux, macOS and Windows and runs the server's normal shutdown path.
- Fall back to the existing escalation (terminate, then kill) if the server does not exit in time.
- No change to the exit-code contract: a graceful stop exits with code 0; the monitor's own stops go through `stop()` and are never mistaken for an intentional `stop`-RPC shutdown.
- The first CI test that runs the real server child process on Linux, Windows and macOS.

## Non-goals

- Windows Job Objects to clean up orphaned plugin helpers (separate follow-up).
- Changing how the `stop` RPC or the exit-code-0 rule works.
- Console control events (`CTRL_BREAK_EVENT`), or moving the server off `multiprocessing`.

## Approaches considered

- **A. A stop request over a `multiprocessing` event (chosen).** Same on every OS, keeps POSIX behaviour, works when RPC is wedged.
- **B. A shutdown RPC the monitor calls.** Simple, but a restart usually happens because the server stopped answering, so it would often fall back to the hard kill anyway.
- **C. `CTRL_BREAK_EVENT` with a process group.** Needs the server launched as a process group, which `multiprocessing` does not offer; a bigger change for the same result.

## Design

**Stop request.** `ServerProcess` owns a `multiprocessing.Event` (`_stop_event`), cleared at the start of every `start()` so a restarted server does not see the previous request. It reaches the child through the process object (pickled at spawn on Windows and macOS, inherited on POSIX; the builder verifies this works under `spawn`).

**Child side.** `_run_server` starts a daemon watcher thread that waits on the event and then performs the same action as `_signal_handler` (close the RPyC server; the existing `finally` destroys the managers; the child then exits with code 0). A request that arrives before the RPyC server exists must not be lost: the watcher keeps waiting until the server is set, or `_run_server` checks the event just before `server.start()`. The SIGTERM/SIGINT handlers stay as they are.

**Monitor side.** `ServerProcess.stop()` becomes: set the event; `join` for `server.stop_timeout` seconds (new setting, default 10: room for plugin shutdown, which itself escalates after a few seconds per plugin); if still alive `terminate()` and `join(5)` (as today); if still alive `kill()`. The escalation lives in a small module-level function that takes a `multiprocessing.Process`, the event and the timeouts, so it can be tested with a plain child process that ignores the event.

**Exit-code contract.** After a graceful stop `exit_code` is 0, exactly as after SIGTERM today. `ServerMonitor._restart_server` calls `stop()` and `start()` itself, so it never reaches the "server died with code 0 means intentional stop" branch; a test pins that a monitor-initiated restart keeps the monitor running.

**Tests.**
- Unit: the escalation function with a real child that exits on the event, one that ignores the event (escalates to terminate), and one that ignores terminate too where the platform allows (escalates to kill); the event is cleared by a new `start()`; a stop request before the RPyC server exists still ends the process.
- Integration (runs on Linux, Windows and macOS, marked so skips are explicit): start the real server child with a temporary prefix and a free port; wait for a good `heartbeat` over RPyC; `stop()` and assert it exited with code 0 without needing `kill()` (a hard kill never gives 0); then a real `ServerMonitor` restart: heartbeat works again afterwards and the monitor did not stop. If a test plugin can be installed cheaply into the temporary prefix (the fixture plugin with the portable launcher from `tests/portable.py`), also assert its process is gone after the stop; otherwise record that as not covered.

**Docs.** `DAEMON.md` (Platform notes), `docs/platform-support.md` (footnote on Windows termination, the Server and monitor row), `CLAUDE.md` (fault-tolerance model) describe the new stop sequence and `server.stop_timeout`; the Windows hard-kill statements are removed. `defaults.yml` gains `server.stop_timeout`.

## Left to the builder

Where exactly the event is created and passed; the name and home of the escalation function; how the integration test finds a free port and waits for readiness; test timeouts that are generous on slow runners.

## Risks

This is the first time the real server child runs under `spawn` (Windows, macOS) in CI, so the integration test may reveal other problems (pickling the process object, the hidapi import in the child, the port staying busy between a stop and a restart, logging setup). The builder triages them and stops for a decision if one needs a design change.
