# Decker Server

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE.md)
[![Made with Python](https://img.shields.io/badge/Made%20with-Python-ff7b3f.svg)](https://www.python.org/)

> :warning: Decker Server is currently in early alpha release and doesn't work! Dont use at this point.

**Decker** is an linux application designed for Elgato Stream Deck, inspired by
[StreamController](https://github.com/StreamController/StreamController).

**Decker Server** is the server component/application that handles interacting with the hardware.

## Supported Devices

Decker supports the following Elgato Stream Deck models:

- Stream Deck XL

## Features

None so far (it can list devices)!

## System Requirements

**Decker Server** depends on the following libraries to be installed:

- libhidapi
- [uv](https://docs.astral.sh/uv/), needed to install plugins that have a Python runtime (it builds each plugin's
  own environment)

For installation/setup for common distributions see the subsections below.

### Debian/Ubuntu

`sudo apt-get update sudo apt-get install -y libhidapi-libusb0`

### Fedora

`sudo dnf install hidapi`

### Arch Linux

`sudo pacman -S hidapi`

## Plugins

Key actions and icon packs come from plugins, shipped as `.deckerplugin` packages. Each plugin runs in its own
process, so a misbehaving plugin cannot take the server down. Plugins run with your user's permissions and are not
sandboxed: only install plugins you trust.

```bash
poe cli plugin new com.example.hello          # scaffold a plugin
poe cli plugin pack com.example.hello         # build com.example.hello-0.1.0.deckerplugin
poe cli plugin install com.example.hello-0.1.0.deckerplugin
poe cli plugin list
poe cli plugin remove com.example.hello
```

You can also install from Settings, Plugins in the client, or by dropping a package on the main window. Installing
is only allowed from the server's own machine unless `server.allow_remote_plugin_install` is `true`.

Plugins can also come from repositories: Settings, Plugins, "Get More Plugins…" lets you search, install and update
plugins from the repositories you have added (the default is `https://valsr.github.io/decker-plugins/index.json`).
Decker checks them for updates daily, weekly (default), monthly or only on demand and shows a notification when updates
are available. A repository can provide any plugin and plugins run with your user's permissions, so only add
repositories you trust. See [plugin repositories](docs/plugins/repositories.md), including how to host your own.

Writing a plugin: see the [plugin documentation](docs/plugins/README.md) (package format and manifest, settings
schema, protocol, Python SDK and limits).

## Contributing

Maybe later

## Note

This application is not affiliated with Elgato and/or any of their products and services.
