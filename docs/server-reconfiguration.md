# Server reconfiguration from the client

The client's Settings > Server tab can change some of the server's own settings, but only when the server was started
with `--allow-client-reconfiguration`. Otherwise those options are greyed out.

## The flag

| Form | Who may change settings |
|------|-------------------------|
| flag absent | nobody, not even clients on the server's machine |
| `--allow-client-reconfiguration` | any connected client |
| `--allow-client-reconfiguration HOST [HOST ...]` | clients connecting from the listed hosts (IPs or names, resolved once at start) and from the server's own machine |

The flag exists only for the running server process. It is never written to the config, so a client cannot grant
itself the right. The server has no authentication: allow only networks you trust.

## What can be changed

| Setting | Config key | Applied |
|---------|------------|---------|
| Port | `server.port` | restart |
| Memory limit (MiB) | `server.memory_limit` | restart |
| Max image file size (KiB) | `icons.max_file_size` | restart |
| Stop when the last client disconnects | `server.stop_when_last_client_leaves` | immediately |

The host field only sets where the client connects; the server's own listen host (`server.host`) is never changed from
a client. Without the flag, the port field also only sets the client's target.

`icons.max_file_size` is the largest image file the icon library accepts (imports, icon packs, GIFs, plugin icons);
the default is 4 MiB. Limits when set from a client: port 1-65535, memory 128 MiB and up, image size 64 KiB - 64 MiB.

## How a change is applied

1. The client calls `server_settings_set` with the changed values. The server validates, writes its config and, for a
   restart-needing change, exits with code `75` after replying.
2. The monitor treats `75` as "restart me with the new settings": it re-reads the config, rebuilds its server handle
   and starts the server again.
3. If the new server does not answer within `server.apply_timeout` (default 60 s), for example because the port is in
   use, the monitor writes the last settings that worked back and restarts on them. The Server tab shows the reason.
4. The client reconnects. If it cannot reach the server on the new port within 30 seconds, it restores its own previous
   port.

Exit code `0` is still an intentional stop and ends the monitor; it is never restarted.

## Stop when the last client disconnects

With the option on, the server shuts down (and the monitor with it) once the last client has been gone for
`server.stop_grace` seconds (default 10), so a quick reconnect does not stop it. It never stops before a client has
connected. Only the GUI client counts as a client: the monitor's health checks and CLI calls do not keep the server
alive.

## Limitation

Other clients connected when the port changes keep their old port and will not follow it; change their port setting
by hand.

The CLI lists the two RPCs, `server_settings` and `server_settings_set`, with `poe cli list`.
