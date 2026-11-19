# Python SDK and CLI quick start

`decker_plugin_sdk` is a small, dependency-free package that Decker provides to Python plugins. It runs the stdio
loop, redirects `print` and any stray output to stderr (the protocol pipe is protected), and maps handler calls to
the [protocol](protocol.md). Handlers run off the reading thread, so a slow handler does not block `ping`.

## Create, pack and install

```bash
poe cli plugin new com.example.hello      # scaffold ./com.example.hello (manifest, plugin.py, icons)
poe cli plugin pack com.example.hello     # validate and write com.example.hello-0.1.0.deckerplugin
poe cli plugin install com.example.hello-0.1.0.deckerplugin
poe cli plugin list
poe cli plugin remove com.example.hello
```

- `install` uploads the package to the running server, prints progress while the environment is built and exits
  with a non-zero status if the install fails. It works without restarting anything. Only one install or uninstall
  runs at a time; a second one is refused with a "busy" error.
- Installing is only allowed from the server's own machine unless `server.allow_remote_plugin_install` is `true`.
- `uv` must be installed on the server machine for plugins with a `python` runtime.

## A minimal action

```python
from decker_plugin_sdk import ActionContext, DeckerPlugin, action


@action("com.example.hello.greet")
class Greet(DeckerPlugin):
    def on_will_appear(self, ctx: ActionContext) -> None:
        ctx.set_title(ctx.settings.get("name", "world"))

    def on_press(self, ctx: ActionContext) -> None:
        ctx.set_title("Hello!")
```

## Handlers (override what you need)

`on_will_appear`, `on_will_disappear`, `on_key_down`, `on_key_up`, `on_press`, `on_double_press`, `on_long_press`,
`on_settings_changed`, `on_global_settings_changed`, plus `gestures(settings)` which may return a set of `Gesture`
values for this key (return `None` to keep the manifest's list).

## Fonts

Decker bundles the DejaVu family (Sans, Sans Condensed, Sans Mono, Serif, Serif Condensed; regular, bold, italic or
oblique, bold italic) and sets `DECKER_FONT_DIR` to its folder for every plugin process on every OS.
`decker_plugin_sdk.fonts.font_path(family="DejaVu Sans", bold=False, italic=False)` returns the absolute path of a face,
or `None` when the variable is unset, the family is unknown or the file is missing; it never raises. It is not exported
from the package root, and an older Decker has no `decker_plugin_sdk.fonts` module, so guard the import:

```python
try:
    from decker_plugin_sdk.fonts import font_path
except ImportError:  # older Decker
    def font_path(family: str = "DejaVu Sans", bold: bool = False, italic: bool = False) -> str | None:
        return None

path = font_path(bold=True)
font = ImageFont.truetype(path, 24) if path else ImageFont.load_default(24)  # None: use your own default
```

Sized `ImageFont.load_default(size)` needs Pillow >= 10.1.

## ActionContext

Attributes: `context`, `action`, `device`, `key_index`, `column`, `row`, `settings`, `global_settings`, `state`.

Methods: `set_image(data, format="png")`, `set_icon(ref, color=None)` (show an icon from an installed icon pack or one of Decker's System Icons, see
[protocol](protocol.md#images)), `clear_image()`, `set_title(title)`, `set_state(n)`, `show_alert()`,
`show_ok()`, `set_settings(dict)` (send only the keys you changed), `set_global_settings(dict)`, `switch_page(to="next", wrap=False)`
(`next`, `previous`, `first`, `last`), `go_to_page(page_id)` (see [Pages](protocol.md#pages)), `switch_profile(to="next", wrap=False)`, `go_to_profile(profile_id)` (see [Profiles](protocol.md#profiles)), `open_url(url)`, `log(message, level="info")`.

The SDK accepts either `global_settings` or `settings` as the key in `global_settings_changed`; the server sends
`global_settings`.
