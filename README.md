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

For installation/setup for common distributions see the subsections below.

### Debian/Ubuntu

`sudo apt-get update sudo apt-get install -y libhidapi-libusb0`

### Fedora

`sudo dnf install hidapi`

### Arch Linux

`sudo pacman -S hidapi`

## Contributing

Maybe later

## Note

This application is not affiliated with Elgato and/or any of their products and services.
