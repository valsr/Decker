# Server Reconfiguration From the Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Settings > Server tab change the server's port, memory limit, library max image file size and stop-on-last-client, gated by `--allow-client-reconfiguration [HOST ...]`, with restart and rollback handled by the monitor.

**Architecture:** A settings RPC validates and writes config; restart-needing changes make the server exit with code 75, which the monitor (already restarting on non-zero exits) handles by re-reading config, rebuilding its server handle and rolling back to the last good values if the new server does not start. The client reads settings and greys controls out when the server says it is not reconfigurable.

**Tech Stack:** Python 3.14, RPyC, PyQt6, pytest + assertpy, YAML config (`decker.common.config`).

**Spec:** `docs/superpowers/specs/2026-11-19-server-reconfiguration-design.md`

## Global Constraints

- Flag meaning: absent = nobody may reconfigure; bare `--allow-client-reconfiguration` = any client; with hosts = those hosts plus loopback. Never persisted to config.
- Host is client-only: `server.host` is never exposed or changed by these RPCs.
- Restart exit code is `75`; exit code `0` still means intentional stop (monitor exits); never restart on `0`.
- Validation: port 1-65535 (int, not bool); memory limit >= 128 MiB; icon max file size 64 KiB - 64 MiB; stop flag bool.
- Stop-when-last-client: grace 10 s; never before a client has connected; a restart is not a disconnect-triggered stop.
- Client rollback: restore previous port if the new target is unreachable within `startup_wait` + margin (30 s).
- Defaults: `icons.max_file_size` 4194304; `server.stop_when_last_client_leaves` false.
- Fault tolerance stays in the monitor; no `start` RPC; the client never touches server files; cross-platform (no POSIX-only calls).
- Code style: black 120, full type annotations, methods < 50 lines, max 5 args, docstrings on public items only. Run `poe format`, `poe mypy`, `poe pylint`, `poe test` before done.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- Port already in use / unbindable: the server must come back on the old port and report the failure (test in Task 5).
- Peer address forms: `127.0.0.1`, `::1`, `::ffff:127.0.0.1` all count as loopback; listed IPv6 hosts match (Task 2).
- Junk values: port `0`, `True`, `"80"`, negative or huge memory/size, missing keys, unknown keys (Task 3).
- Two clients: a second `server_settings_set` while a restart is pending is rejected; other connected clients keep their old port and will not follow (documented limitation, Task 8).
- Last-client disconnect caused by the restart itself, or a client reconnecting inside the grace period, must not stop the server (Task 6).

---

### Task 1: Configurable library max image file size

**Files:**
- Modify: `src/decker/common/config/defaults.yml`, `src/decker/plugin/icons.py:6`, `src/decker/animation/gif.py`, `src/decker/asset/iconpack.py`, `src/decker/asset/iconresize.py`, `src/decker/asset/renderer.py`
- Test: `tests/plugin/test_icons.py` (create if absent)

**Interfaces:**
- Produces: `def max_icon_bytes() -> int` in `decker.plugin.icons` (reads `icons.max_file_size`); `MAX_ICON_BYTES` removed, every importer calls the function at use time.

- [ ] **Step 1: Failing test** `test_max_icon_bytes_follows_config`: `config.set("icons.max_file_size", 1024)` then `assert_that(max_icon_bytes()).is_equal_to(1024)`; `test_max_icon_bytes_default_is_4_mib` asserts `4 * 1024 * 1024`; `test_icon_import_rejects_over_limit` sets 1024 and expects `ImageImportError` from `iconresize` for a 2 KiB PNG.
- [ ] **Step 2:** Run `poe test tests/plugin/test_icons.py` — Expected: FAIL (`max_icon_bytes` undefined).
- [ ] **Step 3:** Add `icons:\n  max_file_size: 4194304` to `defaults.yml` with a one-line comment; implement `max_icon_bytes()` and replace every `MAX_ICON_BYTES` use (grep to find them all).
- [ ] **Step 4:** Run the three tests plus `poe test tests/asset tests/animation` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: make the library max image file size configurable`

### Task 2: Reconfiguration policy and the flag

**Files:**
- Create: `src/decker/server/reconfigure.py`
- Modify: `src/decker/server/app.py` (parser, context assignment), `src/decker/common/context.py` (`ServerAppContext.allow_client_reconfiguration: list[str] | None = None`)
- Test: `tests/server/test_reconfigure.py`, `tests/server/test_app.py`

**Interfaces:**
- Produces: `RESTART_EXIT_CODE: int = 75`; `class ReconfigurePolicy` with `__init__(self, hosts: list[str] | None)` (`None` = disabled, `[]` = any client, otherwise listed hosts resolved once plus loopback) and `def allows(self, peer_host: str | None) -> bool`.

- [ ] **Step 1: Failing tests** (names and assertions): `test_disabled_denies_everyone` (`ReconfigurePolicy(None).allows("127.0.0.1")` is False); `test_bare_allows_any` (`[]` allows `"10.1.2.3"` and `None` peer is False); `test_list_allows_listed_and_loopback` (`["10.0.0.5"]` allows `10.0.0.5`, `127.0.0.1`, `::1`, `::ffff:127.0.0.1`, denies `10.0.0.6`); `test_hostname_resolved_once` (`["localhost"]`). In `test_app.py`: `create_parser().parse_args([]).allow_client_reconfiguration is None`; bare flag gives `[]`; `--allow-client-reconfiguration 10.0.0.5 host2` gives both.
- [ ] **Step 2:** Run `poe test tests/server/test_reconfigure.py tests/server/test_app.py` — Expected: FAIL.
- [ ] **Step 3:** Implement the module (use `ipaddress`, treat IPv4-mapped IPv6 as its IPv4 form) and the argparse option `nargs="*"`, `default=None`, `metavar="HOST"`; assign to `app_context.allow_client_reconfiguration`.
- [ ] **Step 4:** Run the same tests — Expected: PASS.
- [ ] **Step 5: Commit** `feat: add the --allow-client-reconfiguration server flag and policy`

### Task 3: Settings model, validation and persistence

**Files:**
- Create: `src/decker/server/settings.py`
- Modify: `src/decker/common/config/defaults.yml` (`server.stop_when_last_client_leaves: false`)
- Test: `tests/server/test_settings.py`

**Interfaces:**
- Consumes: `decker.common.config` get/set.
- Produces: `@dataclass(frozen=True) class ServerSettings: port: int; memory_limit: int; icon_max_file_size: int; stop_when_last_client_leaves: bool`; `def read_settings() -> ServerSettings`; `def validate(values: dict[str, object]) -> ServerSettings` raising `SettingsError(str)` (partial dicts merge over current values; unknown keys rejected); `def write_settings(new: ServerSettings) -> bool` returns True when a restart is needed (port, memory limit or image size changed) and writes `server.port`, `server.memory_limit`, `icons.max_file_size`, `server.stop_when_last_client_leaves`.

- [ ] **Step 1: Failing tests:** `test_read_defaults`; `test_validate_rejects` parametrized over port `0`, `65536`, `True`, `"80"`, memory `1`, size `1`, size `10**12`, unknown key `host`, stop flag `"yes"`; `test_validate_merges_partial`; `test_write_reports_restart_only_for_restart_keys` (stop flag alone -> False; port -> True) and values land in config.
- [ ] **Step 2:** Run `poe test tests/server/test_settings.py` — Expected: FAIL.
- [ ] **Step 3:** Implement. Memory minimum `128 * 1024 * 1024`; size range `64 * 1024`..`64 * 1024 * 1024`.
- [ ] **Step 4:** Run — Expected: PASS.
- [ ] **Step 5: Commit** `feat: add validated server settings`

### Task 4: RPCs and the restart exit

**Files:**
- Modify: `src/decker/server/service.py` (new RPCs next to `stop`), `src/decker/server/server_context.py` (fields `reconfigure_policy: ReconfigurePolicy`, `restart_requested: bool = False`, `last_apply_error: str | None = None`), `src/decker/server/server.py` (build the policy from `app_context`, `sys.exit(RESTART_EXIT_CODE)` after the normal shutdown when `restart_requested`)
- Test: `tests/server/test_service.py`, `tests/server/test_server_process.py`

**Interfaces:**
- Consumes: Tasks 2-3.
- Produces: RPC `server_settings() -> str` (JSON: the four settings plus `reconfigurable: bool` for the calling peer and `last_apply_error: str | None`); RPC `server_settings_set(values_json: str) -> str` (JSON `{"ok": bool, "restarting": bool, "error": str | None}`); rejects when `_reconfigure_allowed()` is False, on `SettingsError`, and when `restart_requested` is already set. On a restart-needing change: write, set `restart_requested`, reply, then close the server after ~0.1 s (same pattern as `stop`).

- [ ] **Step 1: Failing tests** (service level, real config): `test_settings_readable_by_everyone`; `test_set_rejected_when_flag_absent` (error text names `--allow-client-reconfiguration`, config unchanged); `test_set_applies_stop_flag_live_without_restart`; `test_set_port_requests_restart` (`restarting` true, `restart_requested` set, closes server); `test_second_set_while_pending_rejected`; `test_reconfigurable_reflects_peer`. Process level in `test_server_process.py` (same skip-if-hardware convention): start the real server child with the flag, call `server_settings_set({"port": N})`, assert the child's `exit_code == 75`.
- [ ] **Step 2:** Run `poe test tests/server/test_service.py -k settings tests/server/test_server_process.py` — Expected: FAIL.
- [ ] **Step 3:** Implement the RPCs with `_reconfigure_allowed()` mirroring `_install_allowed()` (`self._context.reconfigure_policy.allows(self._peer_host)`); in `_run_server` exit with 75 only after managers are destroyed.
- [ ] **Step 4:** Run the same tests — Expected: PASS.
- [ ] **Step 5: Commit** `feat: add server_settings RPCs and the restart exit code`

### Task 5: Monitor reload and rollback

**Files:**
- Modify: `src/decker/server/monitor.py` (`_restart_server`, new `_reload_settings`, last-good snapshot), `src/decker/server/server.py` only if `ServerProcess` needs a re-create helper
- Test: `tests/server/test_monitor.py` (+ `tests/server/test_server_process.py` for the real-process rollback)

**Interfaces:**
- Consumes: `RESTART_EXIT_CODE`, `read_settings`, `write_settings` (Task 3), `ServerContext.last_apply_error` is not reachable from the monitor, so the monitor stores the failure in config key `server.last_apply_error` (str, cleared on success) that `server_settings` returns.
- Produces: after a child exit, the monitor re-reads `server.port`, `server.startup_wait`, `server.memory_limit`, rebuilds `ServerProcess` and `ApiHandler`; snapshots the settings after each healthy start; if a start after a restart request fails (process not alive or heartbeat fails within `startup_wait`), it restores the snapshot with `write_settings`, records `server.last_apply_error`, and starts again.

- [ ] **Step 1: Failing tests:** `test_restart_request_rebuilds_with_new_port` (config port changed, child exits 75 -> monitor's `_server.port` and `_api` port equal the new port); `test_failed_start_rolls_back_to_last_good` (occupy the new port with a real socket, child cannot bind, monitor ends on the old port with `server.last_apply_error` set); `test_code_zero_still_stops_monitor`; `test_memory_limit_change_applies_after_restart`.
- [ ] **Step 2:** Run `poe test tests/server/test_monitor.py` — Expected: FAIL.
- [ ] **Step 3:** Implement; keep `_check_once` under 50 lines by extracting `_reload_settings()` and `_rollback()`.
- [ ] **Step 4:** Run — Expected: PASS.
- [ ] **Step 5: Commit** `feat: reload settings and roll back failed reconfiguration in the monitor`

### Task 6: Stop when the last client leaves

**Files:**
- Modify: `src/decker/server/service.py` (`on_connect`/`on_disconnect`), `src/decker/server/server_context.py` (a small `ClientTracker`, shared across connections because a service instance is created per connection)
- Test: `tests/server/test_client_tracker.py`

**Interfaces:**
- Produces: `class ClientTracker` with `__init__(self, grace: float, on_idle: Callable[[], None])`, `def connected(self) -> None`, `def disconnected(self) -> None`; `on_idle` fires once after `grace` seconds with zero clients, only if a client has connected since start, cancelled by a new `connected()`; module const `LAST_CLIENT_GRACE = 10.0`. The service calls `on_idle` only when `server.stop_when_last_client_leaves` is true, and it closes the server so the exit code is 0.

- [ ] **Step 1: Failing tests** (small grace e.g. 0.05): `test_fires_after_grace_when_last_leaves`; `test_never_fires_before_first_connect`; `test_reconnect_within_grace_cancels`; `test_two_clients_one_leaves_does_not_fire`; `test_flag_off_never_stops`; `test_exit_code_is_zero_on_idle_stop` (process level, same convention as Task 4).
- [ ] **Step 2:** Run `poe test tests/server/test_client_tracker.py` — Expected: FAIL.
- [ ] **Step 3:** Implement with a lock and `threading.Timer`; ensure a restart-triggered shutdown (`restart_requested`) never reaches `on_idle`.
- [ ] **Step 4:** Run — Expected: PASS.
- [ ] **Step 5: Commit** `feat: stop the server when the last client leaves, optionally`

### Task 7: Client Server tab

**Files:**
- Modify: `src/decker/client/connection_manager.py` (parse `server_settings` after connect into `ConnectionManager.server_settings: ServerSettingsInfo | None`), `src/decker/client/widgets/settings_dialog.py` (`_build_server_tab`, `_load_from_config`, `_apply_server`), `src/decker/client/config.py` if a helper is needed
- Test: `tests/client/test_connection_manager.py`, `tests/client/widgets/test_settings_dialog.py` (offscreen Qt)

**Interfaces:**
- Consumes: RPCs from Task 4 via `ConnectionManager.call`.
- Produces: `@dataclass(frozen=True) class ServerSettingsInfo: port: int; memory_limit: int; icon_max_file_size: int; stop_when_last_client_leaves: bool; reconfigurable: bool; last_apply_error: str | None`; `ConnectionManager.set_server_settings(values: dict[str, object]) -> tuple[bool, str | None]`; dialog widgets: memory limit and image size in MiB spin boxes, stop checkbox, all of them (not host) disabled with a tooltip naming the flag when `reconfigurable` is false, and the port field only changes the client target in that case.

- [ ] **Step 1: Failing tests:** `test_fields_disabled_when_not_reconfigurable` (host/port enabled, the rest disabled); `test_fields_enabled_when_reconfigurable`; `test_apply_sends_changed_values_and_updates_client_port`; `test_host_change_never_sent_to_server`; `test_unreachable_new_port_reverts_client_port` (fake clock/timeout 30 s, restores previous port and shows `last_apply_error`); `test_not_reconfigurable_port_change_only_changes_client_target`.
- [ ] **Step 2:** Run `poe test tests/client -k "settings"` — Expected: FAIL.
- [ ] **Step 3:** Implement; keep the revert timer on the Qt side (`QTimer`), reconnect through `request_reconnect()` (the `ReconnectWaitingOverlay` already covers the gap).
- [ ] **Step 4:** Run — Expected: PASS.
- [ ] **Step 5: Commit** `feat: configure the server from the client Server tab`

### Task 8: Docs and quality gates

**Files:**
- Modify: `README.md` (feature table row "Server configuration from the client"; platform table row with `⚠️` until the PR's CI run is green, then `✅` with the run id in a footnote), `CLAUDE.md` (server fault-tolerance section: exit code 75, the flag, `server_settings` RPCs), `docs/platform-support.md` only if the tiers text changes
- Create: `docs/server-reconfiguration.md` (the flag forms, what each setting does, the rollback behaviour, the limitation that other connected clients keep their old port)

- [ ] **Step 1:** Write the docs above.
- [ ] **Step 2:** Run `poe format && poe mypy && poe pylint && poe test` — Expected: all pass, pylint >= 9.0, coverage >= 85%.
- [ ] **Step 3:** Push and open a PR; once CI is green update the README platform row and footnote with the run id.
- [ ] **Step 4: Commit** `docs: document server reconfiguration`

## Self-review

Spec coverage: flag semantics (Task 2), settings and validation (Task 3), RPCs and restart code (Task 4), monitor reload and rollback (Task 5), stop-when-last-client (Task 6), client tab, greying out, port revert and client-only host (Task 7), docs and platform row (Task 8), icon size limit (Task 1). Review Focus items map to Tasks 2-6 and 8.
