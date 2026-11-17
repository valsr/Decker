#!/usr/bin/env python3
"""Stdlib-only counter used by the tests; speaks the plugin protocol directly so it needs no SDK or venv."""

import base64
import json
import struct
import sys
import zlib


def _png(count):
    """8x8 RGBA image, transparent except a centre block whose colour depends on the count."""
    shade = (count * 37) % 200 + 40
    clear, ink = b"\x00\x00\x00\x00", bytes((shade, 255 - shade, 128, 255))
    rows = [b"\x00" + b"".join(ink if 3 <= x <= 4 and 3 <= y <= 4 else clear for x in range(8)) for y in range(8)]
    raw = b"".join(rows)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 8, 8, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _send(event, context=None, payload=None):
    data = {"event": event}
    if context is not None:
        data["context"] = context
    if payload:
        data["payload"] = payload
    print(json.dumps(data), flush=True)


class Counter:
    def __init__(self):
        self.count = 0
        self.settings = {}

    def push(self, context):
        wanted = ["press", "long_press"]
        if self.settings.get("double_step") is not None:
            wanted.append("double_press")
        _send("set_gestures", context, {"gestures": wanted})
        _send("set_image", context, {"image": base64.b64encode(_png(self.count)).decode(), "format": "png"})

    def advance(self, amount):
        self.count += amount
        limit = self.settings.get("max", 0)
        if limit > 0 and self.count >= limit:
            self.count = 0

    def handle(self, event, context, payload):
        if event == "will_appear":
            self.count = 0
            self.settings = payload.get("settings", {})
        elif event == "settings_changed":
            self.settings = payload.get("settings", {})
        elif event == "press":
            self.advance(self.settings.get("step", 1))
        elif event == "double_press":
            self.advance(self.settings.get("double_step") or 0)
        elif event == "long_press":
            self.count = 0
        else:
            return
        self.push(context)


def main():
    counter = Counter()
    for line in sys.stdin:
        message = json.loads(line)
        event = message["event"]
        if event == "hello":
            _send("ready")
        elif event == "ping":
            _send("pong")
        elif event == "shutdown":
            break
        else:
            counter.handle(event, message.get("context"), message.get("payload") or {})


main()
