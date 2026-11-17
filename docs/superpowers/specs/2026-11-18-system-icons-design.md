# System icons in the icon library — design

Status: approved in conversation. Size: small project (one repo: `decker`).

## Intent

Let users pick icons from the system's freedesktop icon theme, exactly like pack icons: they show up in the icon library under a
virtual **System Icons** section, grouped by the usual categories, and a chosen icon behaves like any other icon (key
preview, per-key icon override, plugins' `set_icon`, thumbnails).

## Goals

- **Library:** the picker tree gets a built-in node **System Icons** with children **Actions, Applications, Categories,
  Devices, Emblems, Emotes, Mimetypes, Places, Status, Other** (a child is shown only if it has icons). "All icons" includes
  them; search works as for any pack. No change to the picker is needed beyond what the existing pack tree already does.
- **Virtual packs:** one virtual pack per category with id `decker.system.<category>` (`actions`, `applications`,
  `categories`, `devices`, `emblems`, `emotes`, `mimetypes`, `places`, `status`, `other`). They are listed by
  `iconpacks_list` with `plugin_id = "decker.system"`, `plugin_name = "System Icons"`, and served by `iconpack_icons` /
  `iconpack_icon` like plugin packs. Refs stay `pack:decker.system.<category>/<icon name>`; the icon *name* (no extension,
  no size) is stored, so a ref follows the theme.
- **Theme lookup (server side, no Qt/GTK):** parse `index.theme` of the active theme and its `Inherits` chain, ending at
  `hicolor`, from `$XDG_DATA_HOME/icons`, `~/.icons` and each `$XDG_DATA_DIRS/icons` (default `/usr/share/icons`). A directory's
  `Context` decides its category (`MimeTypes` shown as "Mimetypes"; Animations, Panel, Stock, Legacy, a missing or unknown
  context → Other). The primary theme's icons win over inherited ones with the same name.
- **Which file:** a scalable SVG is preferred; otherwise the largest raster (png/svg/jpg) directory. Symbolic icons are
  included. Only files up to `MAX_ICON_BYTES` are served.
- **Active theme:** the config key `icons.system_theme` if non-empty, else auto-detected from the user's GTK
  (`~/.config/gtk-3.0/settings.ini` `gtk-icon-theme-name`) or KDE (`~/.config/kdeglobals` `[Icons] Theme`) settings, else
  `Adwaita`, else `hicolor`. Default of the key: empty.
- **Cache:** the packs' `plugin_version` is `<theme>-<hash of the theme's index.theme mtimes>`, so changing theme or updating
  it invalidates the client's thumbnails. The icon index is built once on first use (thread-safe) and rebuilt when that
  version changes.
- `read_ref` and plugin `set_icon` resolve system refs through the same code path as plugin packs; an unknown name or an
  uninstalled theme yields no image (the key falls back as it does for a missing pack icon).

## Non-goals

- A theme picker in the GUI; cursor themes; icons outside theme directories (`/usr/share/pixmaps`); live reload on a
  theme change without a request (a server restart or the next index rebuild picks it up); per-size selection by the user.

## Anti-goals

- Blocking the server for long on first use (scan lazily, once, only the needed directories) or holding a lock during file I/O.
- Serving files outside the theme directories (names are looked up in the index, never joined from user input).

## Approaches considered

1. **Server-side virtual packs (chosen)** — fits the existing RPCs, ref format, caches and plugin `set_icon`.
2. Qt's `QIcon.fromTheme` on the client — cannot list icons and ignores that the server owns the files. Rejected.

## Design

- New `src/decker/asset/systemicons.py`: `SystemIcons` with `theme_name() -> str`, `version() -> str`,
  `list_packs() -> list[dict]`, `list_icons(pack_id) -> list[str]`, `read_icon(pack_id, name) -> bytes | None`, and
  `owns(pack_id) -> bool`; pure-Python index builder (`index.theme` parser via `configparser`, `os.scandir` walk).
- `IconPackRegistry` composes a `SystemIcons` (injectable for tests): `list_packs` appends the virtual packs, `list_icons`
  and `read_icon` delegate when `owns(pack_id)`; plugin packs cannot register an id starting with `decker.system.`.
- `defaults.yml`: `icons.system_theme: ""`. Docs: `docs/plugins/protocol.md`/`sdk-quickstart.md` note that `set_icon` accepts
  system icon refs; `CLAUDE.md` mentions the System Icons packs.

## Testing

TDD with a fake theme tree under `tmp_path` (an `index.theme` with directories of several contexts and sizes, an inherited
theme, a hicolor fallback, an SVG and PNG of the same name): categories, context mapping (incl. MimeTypes/Other/missing),
inheritance and precedence, size preference, size limit, unknown/hostile names (`..`, absolute, slash), theme detection
(config key, GTK settings, KDE settings, fallbacks), version changes with mtime, registry delegation and id reservation, RPC
output shape, `read_ref` of a system ref, and a picker test that the tree shows System Icons with its category children
from a fake RPC.

## Left to the builder

Internal index data structure, the hash used for the version, and how Mimetypes/Other labels are capitalised in the UI.
