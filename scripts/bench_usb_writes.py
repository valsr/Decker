#!/usr/bin/env python3
"""Measure how fast a Stream Deck accepts key images over USB.

WARNING: stop the decker server first (`poe cli stop`). This script opens the deck itself, takes the device over,
and rapidly rewrites keys, so the keys will flash. The deck is reset when the script exits.

Usage:
    python scripts/bench_usb_writes.py path/to/animation.gif [--seconds 3]

The GIF's frames are encoded with decker.animation.encode.encode_native at JPEG quality 100 and 90 (BMP decks run
once) and written to 1 key, 8 keys and every key as fast as the deck accepts them. For each run it prints frames/s,
HID reports/s, MB/s and the latency of one set_key_image call (mean, p50, p99).

Reference result on a Stream Deck XL: about 3998 reports/s (4.09 MB/s) at quality 100 (mean 6.4 KB per frame, 1.69 ms
per call) and 3555 reports/s at quality 90 (2.7 KB, 0.84 ms per call), regardless of how many keys were written.
"""

import argparse
import math
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageSequence
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import StreamDeck

from decker.animation.encode import KeyFormat, encode_native

DEFAULT_REPORT_PAYLOAD = 1016
QUALITIES = (100, 90)


@dataclass(frozen=True)
class RunStats:
    """Summary of one timed run of key writes."""

    frames_per_s: float
    reports_per_s: float
    mb_per_s: float
    mean_ms: float
    p50_ms: float
    p99_ms: float


def reports_for(size: int, payload: int) -> int:
    """Number of HID reports needed to send size bytes with payload bytes per report."""
    return max(1, math.ceil(size / payload))


def percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Value at fraction (0..1) of an ascending list, by nearest rank; 0.0 for an empty list."""
    if not sorted_values:
        return 0.0
    rank = min(len(sorted_values) - 1, max(0, math.ceil(fraction * len(sorted_values)) - 1))
    return sorted_values[rank]


def summarize(durations: Sequence[float], sizes: Sequence[int], elapsed: float, payload: int) -> RunStats:
    """Turn per-call durations (s) and payload sizes (bytes) measured over elapsed seconds into run statistics."""
    if not durations or elapsed <= 0:
        return RunStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ordered = sorted(durations)
    return RunStats(
        frames_per_s=len(durations) / elapsed,
        reports_per_s=sum(reports_for(size, payload) for size in sizes) / elapsed,
        mb_per_s=sum(sizes) / elapsed / 1e6,
        mean_ms=statistics.fmean(durations) * 1000,
        p50_ms=percentile(ordered, 0.50) * 1000,
        p99_ms=percentile(ordered, 0.99) * 1000,
    )


def key_counts(total: int) -> list[int]:
    """The key counts to test: 1, 8 and all keys, without duplicates on decks with fewer keys."""
    return sorted({min(1, total), min(8, total), total})


def encode_frames(gif_path: Path, fmt: KeyFormat, quality: int) -> list[bytes]:
    """Encode every frame of the GIF in the deck's native format at quality."""
    with Image.open(gif_path) as gif:
        return [encode_native(frame.convert("RGB"), fmt, quality) for frame in ImageSequence.Iterator(gif)]


def run_once(deck: StreamDeck, frames: Sequence[bytes], keys: int, seconds: float, payload: int) -> RunStats:
    """Write the frames round-robin to the first keys keys for seconds and summarize the timings."""
    durations: list[float] = []
    sizes: list[int] = []
    started = time.perf_counter()
    count = 0
    while time.perf_counter() - started < seconds:
        data = frames[count % len(frames)]
        call_started = time.perf_counter()
        deck.set_key_image(count % keys, data)
        durations.append(time.perf_counter() - call_started)
        sizes.append(len(data))
        count += 1
    return summarize(durations, sizes, time.perf_counter() - started, payload)


def print_row(label: str, quality: int, frames: Sequence[bytes], stats: RunStats) -> None:
    """Print one result line."""
    mean_kb = sum(len(frame) for frame in frames) / len(frames) / 1024
    print(
        f"{label:>9}  q{quality:<3} {mean_kb:5.1f} KB/frame  {stats.frames_per_s:7.1f} frames/s  "
        f"{stats.reports_per_s:7.0f} reports/s  {stats.mb_per_s:5.2f} MB/s  "
        f"call mean {stats.mean_ms:5.2f} ms  p50 {stats.p50_ms:5.2f} ms  p99 {stats.p99_ms:5.2f} ms"
    )


def benchmark(deck: StreamDeck, gif_path: Path, seconds: float) -> None:
    """Run every key count at every quality the deck's image format supports."""
    fmt_info: dict[str, Any] = deck.key_image_format()
    payload = int(getattr(deck, "IMAGE_REPORT_PAYLOAD_LENGTH", DEFAULT_REPORT_PAYLOAD))
    fmt = KeyFormat.from_deck(fmt_info, payload)
    qualities = QUALITIES if fmt.image_format.upper() == "JPEG" else (100,)
    total = int(deck.key_count())
    print(f"{deck.deck_type()}: {total} keys, {fmt.size[0]}x{fmt.size[1]} {fmt.image_format}, payload {payload} B")
    for quality in qualities:
        frames = encode_frames(gif_path, fmt, quality)
        for keys in key_counts(total):
            stats = run_once(deck, frames, keys, seconds, payload)
            print_row(f"{keys} key" + ("s" if keys > 1 else ""), quality, frames, stats)


def find_deck() -> StreamDeck | None:
    """The first Stream Deck XL, else the first deck found."""
    decks = DeviceManager().enumerate()
    xl = [deck for deck in decks if "XL" in deck.deck_type()]
    return (xl or decks or [None])[0]


def main() -> int:
    """Parse arguments, run the benchmark on the first suitable deck and reset it afterwards."""
    parser = argparse.ArgumentParser(
        description="Measure Stream Deck USB image write throughput (server must be stopped)."
    )
    parser.add_argument("gif_path", type=Path, help="GIF whose frames are written")
    parser.add_argument("--seconds", type=float, default=3.0, help="duration of each run (default 3)")
    args = parser.parse_args()
    deck = find_deck()
    if deck is None:
        print("No Stream Deck found.")
        return 1
    deck.open()
    try:
        benchmark(deck, args.gif_path, args.seconds)
    finally:
        deck.reset()
        deck.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
