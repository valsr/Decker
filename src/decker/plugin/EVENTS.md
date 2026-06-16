# Future plugin events and API

Not yet implemented. Documented here so the contract is visible before it exists.

## Inbound events (not yet dispatched)

- `on_dial_rotate` — a Stream Deck+ dial was turned
- `on_title_parameters_changed` — the user edited an action's title font/size/color in the UI
- `on_device_connected` / `on_device_disconnected` — hardware hot-plug
- `on_touch_tap` — the touchscreen strip (Stream Deck+) was tapped

## Outbound API (not yet implemented)

- `ctx.get_global_settings()` / `ctx.set_global_settings()` — plugin-wide settings, distinct
  from per-context settings. Schema extension to `plugins.db` is straightforward when needed:
  a `global_settings` table keyed by `plugin_uuid` alone.
