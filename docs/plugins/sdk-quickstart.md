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

## ActionContext

Attributes: `context`, `action`, `device`, `key_index`, `column`, `row`, `settings`, `global_settings`, `state`.

Methods: `set_image(data, format="png")`, `clear_image()`, `set_title(title)`, `set_state(n)`, `show_alert()`,
`show_ok()`, `set_settings(dict)`, `set_global_settings(dict)`, `open_url(url)`, `log(message, level="info")`.

The SDK accepts either `global_settings` or `settings` as the key in `global_settings_changed`; the server sends
`global_settings`.
