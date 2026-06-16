#!/usr/bin/env python3
"""Rasterize decker.svg to PNG at standard icon sizes."""

import sys
from pathlib import Path

SIZES = [16, 24, 32, 48, 64, 128, 256, 512]
HERE = Path(__file__).parent
SRC = HERE / "decker.svg"
DEST = HERE / "icons"


def main() -> None:
    try:
        import cairosvg  # type: ignore[import-untyped]
    except ImportError:
        print("cairosvg not installed — run: pip install cairosvg", file=sys.stderr)
        sys.exit(1)

    DEST.mkdir(exist_ok=True)
    for size in SIZES:
        out = DEST / f"decker_{size}.png"
        cairosvg.svg2png(url=str(SRC), write_to=str(out), output_width=size, output_height=size)
        print(f"  {out.relative_to(HERE)}")

    print(f"\nGenerated {len(SIZES)} icons in {DEST.relative_to(HERE.parent.parent.parent)}/")


if __name__ == "__main__":
    main()
