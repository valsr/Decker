# Protocol

Decker talks to each plugin process over its **stdin/stdout**. Every message is one JSON object per line (UTF-8,
terminated by `\n`):

```json
{"event": "set_title", "context": "ctx-1", "payload": {"title": "Hi"}}
```

- `event`: required string.
- `context`: Decker's id for one key instance of an action. Omitted for plugin-wide events.
- `payload`: object, omitted when empty.

stdout is reserved for the protocol. Anything a plugin writes to **stderr** is logged by the server with the plugin
id as a prefix. Lines that are not valid protocol messages are logged and dropped. A line longer than 8 MiB is
discarded.

## Startup

1. The server starts your process and sends `hello`.
2. Send `ready` when you are set up. Until then the server queues events for you; if `ready` does not arrive
   within the ping timeout (10 s) the process is killed.
3. The server sends `will_appear` for every key showing one of your actions, then any events queued meanwhile.

## Server to plugin

| Event | Context | Payload |
|-------|---------|---------|
| `hello` | | `{"protocol": 1, "decker_version": "0.3.0", "plugin_id": "com.example.hello", "global_settings": {...}}` (first message) |
| `will_appear` | yes | `{"action": "<action id>", "device": "<device id>", "key": {"index": 0, "column": 0, "row": 0}, "settings": {...}, "state": 0}` |
| `will_disappear` | yes | none |
| `key_down`, `key_up` | yes | none (raw key events) |
| `press`, `double_press`, `long_press` | yes | none (recognised by the server for the key's registered gestures) |
| `settings_changed` | yes | `{"settings": {...}}` |
| `global_settings_changed` | | `{"global_settings": {...}}` |
| `device_connected` | | `{"device": "<device id>"}` |
| `ping` | | none; reply with `pong` |
| `shutdown` | | none; exit promptly |

(`device_disconnected` is part of the vocabulary but not sent in v1.)

## Plugin to server

| Event | Context | Payload |
|-------|---------|---------|
| `ready` | | none |
| `pong` | | none |
| `set_image` | yes | `{"image": "<base64>", "format": "png"}` (`png`, `jpeg` or `svg`), or `{"image": null}` to clear, or `{"icon": "pack:<pack id>/<path>", "color": "#rrggbb"}` to show an icon from an installed icon pack (see [Images](#images)) |
| `set_title` | yes | `{"title": "text"}`, shown only when the user set no title; titles are one line, so line breaks are drawn as a single space |
| `set_state` | yes | `{"state": 1}`, an index into the action's `states` |
| `show_alert`, `show_ok` | yes | none (accepted, no visible effect in v1) |
| `set_settings` | yes | `{"settings": {...}}`, validated against the action's schema and saved |
| `set_global_settings` | | `{"settings": {...}}`, validated against `global_settings` and saved |
| `set_gestures` | yes | `{"gestures": ["press", "long_press"]}`; replaces the key's gesture set |
| `log` | | `{"level": "info", "message": "text"}`; levels `debug`, `info`, `warning`, `error` |
| `open_url` | | `{"url": "https://..."}`; only `http`/`https` with a host are accepted. Every connected client asks the user before opening it |

Messages for a context that is not active (for example after `will_disappear`) are dropped.

## Images

An icon from an installed icon pack is shown by reference: `{"icon": "pack:<pack id>/<path>", "color": "#rrggbb"}`
(`color` is optional and may be `#rrggbbaa`). The server reads the icon itself, so the plugin never touches pack
files. `image` and `icon` are mutually exclusive (a payload with both is dropped). A reference the server cannot read
(malformed, unknown pack, path outside the pack, too large, pack uninstalled later) clears the image and is logged.
A pack icon is drawn at 70% of the key and centred, so the key's title stays readable around it (images sent with
`image` still fill the key). `color` recolours SVG icons: it sets the SVG's `color` (so `fill="currentColor"` follows it) and a default `fill`, and
the alpha becomes the SVG's opacity. Raster icons ignore it, and an invalid colour leaves the icon untinted.

Raster images larger than 4096 x 4096 pixels are rejected. Decker scales the image to the key and draws it over
the key background, then the title. Invalid base64 is dropped.

## Flood protection and liveness

- Each plugin may send 100 messages per second sustained with a burst of 200. Messages over budget are dropped; a
  plugin that stays over budget for 5 s continuously is killed and counted as a crash.
- The server sends `ping` every 5 s. No `pong` within 10 s counts as a hang and the process is killed.

## Minimal executable plugin

```python
#!/usr/bin/env python3
import json, sys

def send(**message):
    print(json.dumps(message), flush=True)

for line in sys.stdin:
    message = json.loads(line)
    event, context = message["event"], message.get("context")
    if event == "hello":
        send(event="ready")
    elif event == "will_appear":
        send(event="set_title", context=context, payload={"title": "Hello"})
    elif event == "ping":
        send(event="pong")
    elif event == "shutdown":
        break
```
