# Decker plugins

A Decker plugin is a folder that is shipped as a `.deckerplugin` package. This guide describes everything you need
to build one without reading Decker's source.

- [Package and manifest](package-and-manifest.md): archive layout, `manifest.json` fields, contribution kinds
- [Settings schema](settings-schema.md): the field types that generate settings forms
- [Protocol](protocol.md): the newline-delimited JSON messages exchanged with the Decker server
- [Python SDK and CLI quick start](sdk-quickstart.md): `poe cli plugin new|pack|install`
- [Limits, lifecycle and the launch environment](limits.md)
- [Plugin repositories](repositories.md): index format, update checks, hosting your own repository

Presets (`"static"` actions), `{page_name}`-style templates, `page` settings and `switch_page` are described in the manifest, settings-schema and protocol pages above; Decker itself ships one built-in static plugin, Blank.

Plugins run with your user's permissions and are not sandboxed. Only install plugins from authors you trust.

## What a plugin can contribute

| Kind | What it is | Needs a runtime |
|------|------------|-----------------|
| `actions` | Key actions that appear in the action list and run as a separate process | yes |
| `icon_packs` | A folder of images browsable from the image library | no |

Decker draws the key background and title (the user's appearance settings). Your plugin supplies the key image with
`set_image` and may supply a fallback title with `set_title`.

## Known limitations (v1)

- `show_alert` and `show_ok` are accepted but have no visible effect yet. When a plugin fails (crashes repeatedly),
  its keys are cleared and show the label "Plugin failed" in the client; there is no hardware alert animation.
- The plugin process gets a minimal environment (see [limits](limits.md)). Variables such as `DISPLAY`,
  `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` are not passed on, so plugins that talk to the
  desktop session (media keys over D-Bus, notifications, launching GUI programs) will not work without extra effort
  such as locating the session themselves. There is no allow-list setting in v1.
- `device_disconnected` is declared by the protocol but not sent yet; `device_connected` is sent for the devices
  known when the plugin becomes ready.
