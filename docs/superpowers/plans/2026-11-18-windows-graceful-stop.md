# Graceful Server Stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The server monitor stops the server gracefully on every OS (so plugins and stores shut down) and falls back to terminate and kill; a real-child integration test runs on Linux, Windows and macOS.

**Architecture:** `ServerProcess` owns a `multiprocessing.Event`; the child's watcher thread turns a set event into the same shutdown the SIGTERM handler performs, through a small `ShutdownGate` that cannot lose an early request. `stop()` becomes event, wait `server.stop_timeout`, terminate, kill, implemented by a module-level `stop_process` function that is testable with plain child processes.

**Tech Stack:** Python 3.14 `multiprocessing`, RPyC, pytest + assertpy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-18-windows-graceful-stop-design.md`.

## Global Constraints

- Stop sequence in `ServerProcess.stop()`: set the event; `join` for `server.stop_timeout` seconds (new setting in `defaults.yml`, default `10.0`, read inside `stop()` with `config.get_as_or_default`; do NOT add a constructor argument, the argument limit is 5); then `terminate()` and `join(5)`; then `kill()` and `join()`. POSIX still gets SIGTERM from `terminate()`.
- `stop_process(process: multiprocessing.Process, stop_event: multiprocessing.synchronize.Event, grace: float, terminate_wait: float = 5.0) -> str` is a module-level function in `src/decker/server/server.py`; it returns `"graceful"`, `"terminated"` or `"killed"` and never raises for an already-exited process.
- `ShutdownGate` (module level in `server.py`): `request() -> None` records a shutdown request and, if a server is attached, closes it; `attach(server: Closable) -> bool` stores the RPyC server and returns `True` (after closing it) if a request had already arrived, else `False`. `Closable` is a `typing.Protocol` with `close() -> None`. Both are thread-safe. The SIGTERM/SIGINT handler and the event watcher both call `request()`; `_run_server` skips `server.start()` when `attach` returns `True`.
- The event is cleared at the start of every `ServerProcess.start()`. The event reaches the child through the process object (pickled at spawn on Windows and macOS).
- Exit-code contract unchanged: a graceful stop ends with exit code 0; `ServerMonitor._restart_server` keeps calling `stop()` then `start()` and must not shut the monitor down.
- The integration test must not touch real Stream Deck hardware, the user's real `~/.decker`, or port 18861: use a temporary prefix and a free port. If `DeviceManager` cannot be kept away from attached hardware without a product change, STOP and report instead of adding a hook; an automatic skip when a real device is enumerable (with a marker reason naming the feature and its docs row) is acceptable.
- Skips use the registered markers `linux_only` / `posix_only` / `windows_only` with a reason that names the feature and its row in `docs/platform-support.md`; no silent skips.
- Project rules: annotate everything (tests too), methods < 50 lines, max 5 args, docstrings on public items only, black 120. Gates: `poe format`, `poe mypy` (+ `poetry run mypy --platform win32 .` and `--platform darwin .`), `poe pylint` (>= 9.0), `poe test` (coverage >= 85%). Tests use pytest + assertpy, mirror `src/` under `tests/`, prefer real processes over mocks.
- Every commit message: subject line, a BLANK LINE, then the trailer lines `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01FG9NRj5PgFFP8CrgR6aMLZ`.
- The maintainer approved pushing work branches to GitHub to verify on the Windows and macOS runners (`gh workflow run ci.yml --ref <branch>`, `gh run list/watch/view`). Push only the working branch `feat/windows-graceful-stop`; no PR until the matrix is green.

## Review Focus

- A stop request that arrives before the RPyC server exists still ends the process (Task 1 gate tests).
- A child that ignores the event is terminated, and one that ignores terminate is killed, within bounded time; an already-exited child never raises (Task 1).
- A restart after a stop does not see the previous stop request (Task 2).
- A graceful stop exits with code 0, and a monitor-initiated restart does not shut the monitor down (Task 2).
- The integration test never touches real hardware, the real `~/.decker` or port 18861 (Task 2).

---

### Task 1: Stop request, shutdown gate and escalation

**Files:**
- Modify: `src/decker/server/server.py` (`ServerProcess.__init__`, `start`, `stop`, `_signal_handler`, `_run_server`), `src/decker/common/config/defaults.yml`
- Create: `tests/server/test_server_stop.py`

**Interfaces:**
- Produces: `Closable`, `ShutdownGate`, `stop_process`, `ServerProcess._stop_event`, `server.stop_timeout` (all as in Global Constraints).

- [ ] **Step 1: Write failing tests** (module-level child targets so they pickle under `spawn`): `test_gate_closes_the_server_when_a_request_arrives_after_attach` (fake object with `close()`), `test_gate_closes_at_attach_when_the_request_came_first` (`attach` returns True and closed once), `test_gate_attach_without_a_request_returns_false`, `test_gate_request_is_idempotent` (close called once); `test_stop_process_returns_graceful_when_the_child_exits_on_the_event` (child waits on the event then exits 0), `test_stop_process_terminates_a_child_that_ignores_the_event` (child sleeps; use short `grace` and `terminate_wait`; result `"terminated"`), `test_stop_process_kills_a_child_that_ignores_terminate` (POSIX child sets `SIGTERM` to `SIG_IGN`; `posix_only` marker with the reason described above; result `"killed"`), `test_stop_process_on_an_exited_child_does_not_raise` (returns `"graceful"`), and a test that the default `server.stop_timeout` is `10.0` in the loaded config.
- [ ] **Step 2: Run** `poe test tests/server/test_server_stop.py` — expect FAIL (names missing).
- [ ] **Step 3: Implement** the pieces from Global Constraints; the watcher is a daemon thread started first thing in `_run_server` that blocks on `self._stop_event.wait()` and then calls `gate.request()`; `start()` clears the event before spawning; `stop()` reads the timeout from config and delegates to `stop_process`, keeping its existing log lines and return contract (True when stopped, False if an exception occurred).
- [ ] **Step 4: Run** `poe test tests/server` and the three-platform `mypy` runs — expect PASS (existing monitor tests that mock `ServerProcess` stay valid).
- [ ] **Step 5: Commit** `feat: ask the server to stop gracefully before terminating it`.

---

### Task 2: Integration test with the real server child

**Files:**
- Create: `tests/server/test_server_process.py`
- Modify (only if the triage requires it): the smallest fix in `src/decker/server/server.py` for a failure the test uncovers

**Interfaces:**
- Consumes: `ServerProcess`, `ServerMonitor`, `ApiHandler` (`request_as(DeckerServiceStatus, "heartbeat")`), `decker.common.paths.configure`, the config singleton.

- [ ] **Step 1: Write the tests** (each uses a temporary prefix via `tmp_path`, a free port found by binding to port 0, short `startup_wait`, generous overall timeouts for slow runners): `test_graceful_stop_of_the_real_server_exits_with_code_zero` (start `ServerProcess`, poll the heartbeat over RPyC until healthy or fail after a deadline, call `stop()`, assert it returned True, `exit_code == 0` and the process is gone); `test_stop_right_after_start_still_ends_the_process` (request the stop before the RPyC port answers; assert the process ends within the stop timeout and no process is left); `test_restart_after_a_stop_brings_the_server_back` (stop, start again with the same object, heartbeat healthy again — proves the event is cleared); `test_monitor_restart_keeps_the_monitor_running` (a real `ServerMonitor` with config pointing at the temp prefix and free port: start the server through it, call `_restart_server()`, heartbeat healthy afterwards, and `_stop_requested` is False). If a fixture plugin can be installed cheaply into the temporary prefix (see `tests/fixtures/plugins` and `tests/portable.py`), add `test_plugin_process_is_gone_after_a_graceful_stop` asserting the plugin's child pid no longer exists afterwards; otherwise record "plugin shutdown not covered" in the report. Guard against hardware per Global Constraints.
- [ ] **Step 2: Run** `poe test tests/server/test_server_process.py` locally (Linux) — expect the tests to pass or to expose a problem; record RED output if a product fix is needed first.
- [ ] **Step 3:** Fix only what the tests uncover, with the smallest change, and say what it was in the report. If a failure needs a design decision (for example the process object cannot be pickled under `spawn`, or the hardware seam), stop with BLOCKED.
- [ ] **Step 4: Run** `poe test tests/server`, the three-platform `mypy` runs, `poe pylint` — expect PASS.
- [ ] **Step 5: Commit** `test: run the real server child through a graceful stop and a monitor restart`.

---

### Task 3: Docs

**Files:**
- Modify: `DAEMON.md` (Platform notes, stop description, `server.stop_timeout` in the settings table), `docs/platform-support.md` (footnote on Windows termination, the Server and monitor row), `CLAUDE.md` (fault-tolerance model: the stop sequence and the new setting)

- [ ] **Step 1:** Update the three files so they describe the new stop sequence (event, wait `server.stop_timeout`, terminate, kill) and remove every statement that Windows monitor restarts hard-kill the server without a graceful shutdown; keep the orphaned-helper note and the Job Objects follow-up. Mark cells `CI` only where Task 4's runs show the integration test passed on that OS; until then leave the Windows and macOS cells as they are and write the final values in Task 4.
- [ ] **Step 2: Commit** `docs: describe the graceful server stop sequence`.

---

### Task 4: Drive the matrix to green

**Files:** any file a failure needs; `docs/platform-support.md` for the final cells.

- [ ] **Step 1:** Run the local gates, push `feat/windows-graceful-stop`, run `gh workflow run ci.yml --ref feat/windows-graceful-stop`, and read failures with `gh run view <id> --log-failed`.
- [ ] **Step 2:** Fix each failure at its cause (one cause per commit); real failures of the new integration test on Windows or macOS (pickling under `spawn`, port reuse, hidapi in the child, logging) are product findings: fix them minimally and record each. Stop with BLOCKED if a failure needs a design decision or after 6 workflow runs.
- [ ] **Step 3:** When test x3, mypy (both platform runs), format, pylint and build are green, set the `docs/platform-support.md` cells to what the runs prove (the integration test ran and passed per OS) and commit `docs: record graceful-stop CI coverage`. Do not open a PR.
