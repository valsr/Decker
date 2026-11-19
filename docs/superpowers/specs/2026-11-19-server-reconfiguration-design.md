# Server reconfiguration from the client — design

## Intent
Let a user change the server's own settings from the client's Settings > Server tab instead of editing config files
on the server machine. Todo item "Option to quit server on last client close" and "Expose server options in the
client". The server stays in control: it only accepts changes when started with a flag that allows them.

## Goals
- The Server tab edits: port, memory limit, library max image file size, and "stop the server when the last client
  disconnects". Host always stays a client-side setting (where the client connects); the server's own listen host is
  never changed from the client.
- New server flag `--allow-client-reconfiguration [HOST ...]` decides who may change them.
- Changes that need a restart (port, memory limit, image size limit) restart the server through the monitor and
  the client reconnects, on the new port if it changed.
- When reconfiguration is not allowed, every option except host/port is greyed out (host and port then only change
  where the client connects, as today). When allowed, a port change also changes the server's port; a host change
  never touches the server.
- A bad change (e.g. a port already in use) must never leave the user without a working server: the monitor rolls
  back to the last settings that worked.

## Non-goals / anti-goals
- No authentication or per-option permissions; the gate is the flag and the peer address.
- No client control of the server's listen host (`server.host`); no live apply of port/memory/image limit; no editing of other server keys (heartbeat, startup_wait, ...).
- The flag is never persisted to config, so a client cannot grant itself the right to reconfigure.
- Anti-goal: a typo'd port that strands the client with an unreachable server and no way back.

## Constraints
- Decker rules (CLAUDE.md): fault tolerance lives in the monitor; the server never self-heals; exit code 0 means
  intentional stop, any other code restarts; no `start` RPC; all server state changes go through RPCs; the client never
  touches server files; cross-platform (Linux, Windows, macOS), CLI discovers commands via `commands()` so new RPCs
  need no CLI changes; keep docs and `docs/platform-support.md` in step.

## Decisions (the user's)
- **Apply mechanism: exit-code restart.** A settings RPC validates and writes the config, then the server exits with a
  dedicated non-zero "restart requested" code; the monitor, which already restarts on non-zero exits, re-reads the
  config (port, memory limit) and restarts the server on the new values.
- **Flag meaning:** absent = nobody may reconfigure (not even loopback clients); bare flag = any connected client;
  with hosts = only clients connecting from those hosts.
- Image limit means the library's maximum image file size (today the constant `MAX_ICON_BYTES` = 4 MiB in
  `plugin/icons.py`, shared by icon import, GIF decoding, pack reads and the renderer).
- Changing the port (when allowed) restarts the server and the client reconnects. The host field only changes where the
  client connects, even when reconfiguration is allowed.

## Approaches
1. **Exit-code restart (chosen).** Smallest change; the monitor already owns restarts.
2. A control channel on the monitor: cleaner error replies, but a second listener to secure and supervise. Rejected.
3. The client writes the server's config file: breaks the client/server split and fails for remote servers. Rejected.

## Design (calls marked *call* are the author's, not the user's)

**Config keys.** Existing `server.port` and `server.memory_limit` (bytes); `server.host` is not exposed. New in `defaults.yml`:
`icons.max_file_size` (bytes, default 4194304; `MAX_ICON_BYTES` becomes a read of it) and
`server.stop_when_last_client_leaves` (bool, default false).

**Flag.** `--allow-client-reconfiguration` with `nargs="*"` in `server/app.py`, carried in `ServerAppContext`, passed by
the monitor to the server child, held in memory only. Host entries are IPs or hostnames resolved once at server start
*call*; loopback is always included when a host list is given, so a list cannot lock out the local user *call*.
`_reconfigure_allowed()` in the service mirrors `_install_allowed()` using the connection's peer host.

**RPCs** (`service.py`):
- `server_settings() -> {values..., "reconfigurable": bool}` — current values; `reconfigurable` is for the calling
  peer. Readable by every client.
- `server_settings_set(values: dict) -> {"ok": bool, "restarting": bool, "error": str | None}` — rejects when not
  allowed; validates (port 1-65535, memory limit >= 128 MiB, image limit 64 KiB - 64 MiB *call*);
  writes the user config layer; the stop-when-last-client flag applies live; any other change replies first, then the
  server exits with `RESTART_EXIT_CODE` after a short delay so the reply is delivered *call: 75 (EX_TEMPFAIL)*.

**Monitor.** On a child exit with `RESTART_EXIT_CODE` (or any restart) re-read port, startup wait and memory
limit (the host is unchanged) and rebuild its server process handle and API connection before starting. It remembers the last values that
produced a healthy server; if the new child is not healthy within `server.startup_wait`, it writes the last-good
values back to config, restarts on them, and records the failure for the server to report (`server_settings` includes
`last_apply_error`) *call*.

**Stop when the last client leaves.** In `on_disconnect`, when the flag is on and the connected-client count reaches
zero, start a grace timer (10 s *call*, so a client reconnect or network blip does not kill the server); if still zero
at expiry, shut down with exit code 0 (the monitor then exits, as for the `stop` RPC). The server never stops before at
least one client has connected, and a restart does not count as a disconnect.

**Client.** `ConnectionManager` exposes the latest `server_settings`; the Server tab shows host (client-only), port, memory limit
(MiB), image file size limit (MiB) and the stop checkbox. When `reconfigurable` is false the last three plus the
limits are disabled with a tooltip naming the flag. On Apply with reconfiguration allowed: send the port and the
other changes with `server_settings_set`, then store the host/port in client config and reconnect (the existing
`ReconnectWaitingOverlay` covers the gap). If the client cannot connect to the new target within `startup_wait` plus
margin (30 s *call*), it restores its previous port and shows the server's `last_apply_error`. When reconfiguration is
not allowed, host/port edits change only the client's target.

**Docs and tests.** README feature table row; CLAUDE.md and `docs/platform-support.md` rows (cross-platform: exit codes
and the monitor are OS-neutral, tests run on all CI legs); a short doc page for the flag and settings. Tests are
integration-style (real config, real monitor/server process where existing tests do), covering each rule above.

## Left to the builder
Names of helpers and the exact exit-code constant location, the form widgets' layout, how peers are matched
(IPv4/IPv6 forms), and whether live-applying is generalised later.
