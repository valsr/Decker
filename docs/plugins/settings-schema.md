# Settings schema

`global_settings` and each action's `settings` are an ordered list rendered top to bottom as a form.

## Entries

- Section heading: `{ "section": "Title" }`
- Field: `{ "key": "...", "type": "...", "label": "...", "default": ..., ...}`

Common field keys: `key` (unique within the list), `type`, `label`, `default`, `optional` (an empty value is allowed
and stored as `null`), `placeholder`, `help`.

## Types

| Type | Extra keys | Value |
|------|------------|-------|
| `int` | `min`, `max`, `step`, `special_value` (text shown at `min`, e.g. "no limit") | integer |
| `float` | `min`, `max`, `step`, `decimals` | finite number |
| `text` | `multiline` | string |
| `bool` | | boolean |
| `choice` | `options`: `[{ "label": "...", "value": ... }]` (non-empty) | one of the option values |
| `color` | | `#rrggbb` |
| `font` | | font family name |
| `icon` | | a file path (reserved for the icon library) |

## Validation

The **server** validates stored and incoming values against the schema, so a plugin always receives a complete,
typed settings object:

- unknown keys are dropped;
- missing, invalid, out-of-range or non-finite values fall back to the field's default (or `null` when `optional`);
- the client never duplicates defaults.

Settings reach the plugin in `will_appear.settings`, `settings_changed.settings` and, for plugin-wide settings,
`hello.global_settings` and `global_settings_changed.global_settings`. A plugin can write them back with
`set_settings` (per key) and `set_global_settings`; the server validates those too.
