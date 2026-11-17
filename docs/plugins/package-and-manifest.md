# Package and manifest

## Package

- A package is a zip file named `<anything>.deckerplugin`. `manifest.json` is at the **archive root**.
- Entries must use `/` separators. Entries with backslashes, absolute paths, drive letters, `..` components, NUL
  bytes, symlinks, encrypted entries or duplicate names are rejected.
- Installed to `~/.decker/plugins/<plugin id>/`. Python plugins get their own environment in `.venv` inside that
  folder; uninstalling removes both.
- Size caps: see [limits](limits.md).

Build one with `poe cli plugin pack <folder>` (see the [quick start](sdk-quickstart.md)).

## manifest.json

JSON with snake_case keys. Unknown keys are ignored. `format` must be the integer `1`; any other value is rejected.

```json
{
  "format": 1,
  "id": "com.example.hello",
  "name": "Hello",
  "version": "1.0.0",
  "author": "Example",
  "description": "Says hello.",
  "homepage": "https://example.com/hello",
  "icon": "icons/plugin",
  "category": "Utilities",
  "decker": ">=0.2",
  "runtime": {
    "type": "python",
    "entry": "plugin.py",
    "python": ">=3.11",
    "requirements": ["requests>=2"]
  },
  "global_settings": [],
  "contributes": {
    "actions": [
      {
        "id": "com.example.hello.greet",
        "name": "Greet",
        "tooltip": "Press to greet",
        "icon": "icons/greet",
        "gestures": ["press", "long_press"],
        "states": [{ "image": "icons/greet", "title": "Hi" }],
        "appearance": { "background": "#1f618d", "title_position": "bottom" },
        "settings": [
          { "key": "name", "type": "text", "label": "Name", "default": "world" }
        ]
      }
    ],
    "icon_packs": [
      { "id": "com.example.hello.icons", "name": "Hello icons", "path": "iconpack", "description": "Optional" }
    ]
  }
}
```

### Top-level fields

| Field | Required | Notes |
|-------|----------|-------|
| `format` | yes | Integer `1`. |
| `id` | yes | Reverse-domain id matching `^[a-z0-9]+(\.[a-z0-9-]+)+$`, e.g. `com.example.hello`. |
| `name`, `author` | yes | Non-empty strings. |
| `version` | yes | Semantic version `x.y.z` (pre-release/build suffixes allowed). |
| `description`, `homepage`, `category` | no | Strings. |
| `icon` | no | Path inside the package; the extension is optional (looked up as `.svg`, `@2x.png`, `.png`). Values starting with `pack:` are reserved. |
| `decker` | no | Version specifier for Decker, e.g. `>=0.2`. Install is refused if the running server does not satisfy it. |
| `runtime` | for `actions` | See below. |
| `global_settings` | no | [Settings schema](settings-schema.md) for plugin-wide settings, shown in Settings, Plugins. |
| `permissions` | no | Reserved, ignored in v1. |
| `contributes` | yes | Object keyed by contribution kind; must be non-empty. An unknown kind is refused with "requires a newer version of Decker". |

### `runtime`

| Field | Notes |
|-------|-------|
| `type` | `python` or `executable`. |
| `entry` | Path to the entry file inside the package. Must resolve inside the plugin folder. |
| `python` | Optional interpreter version or specifier for `uv` (python runtime only). A request below Python 3.10 is refused or raised to `>=3.10`, because the SDK needs 3.10+. |
| `requirements` | Python runtime only: pip requirement strings (name, version specifier, extras, markers). URL, git and local-path requirements are rejected. Installed with `uv` from the package index. |

- `python`: Decker runs `python -m decker_plugin_sdk <entry>` in the plugin's own `.venv`. The SDK is provided by
  Decker (you do not list it in `requirements`). `uv` must be installed on the server machine.
- `executable`: Decker runs `entry` directly (any language). The file must be executable; the installer sets the
  executable bit. You implement the [protocol](protocol.md) yourself.

### `actions[]`

| Field | Notes |
|-------|-------|
| `id` | Must start with `<plugin id>.` (same pattern as plugin ids). |
| `name`, `tooltip`, `icon` | Display data. |
| `gestures` | Default gesture set: any of `press`, `double_press`, `long_press` (default `["press"]`). A running plugin can change it per key with `set_gestures`. |
| `states` | Optional list of `{image, title}`; selected by `set_state` (index into the list). |
| `appearance` | Optional defaults for the Decker-drawn appearance (`background`, `show_title`, `title`, `title_position`, `title_font`, `title_size`, `title_color`, `title_outline`, `title_outline_width`). |
| `settings` | [Settings schema](settings-schema.md) for the per-key form. |

### `icon_packs[]`

`{id, name, path, description?}`. `id` starts with the plugin id. `path` is a folder inside the package holding
image files (`svg`, `png`, `jpg`, `jpeg`), optionally ordered by an `icons.json` index. Icon packs
need no `runtime`. Packs are served to clients over RPC; individual icons are limited in size.

## Where plugins come from

Decker ships no plugins. Plugins are installed from a `.deckerplugin` package or from a plugin repository
(see [repositories](repositories.md)); the default repository publishes the Counter plugin.
