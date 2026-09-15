#!/usr/bin/env python3
"""Generate colour-coded .icns variants from a source icon.

The source icon is a dark glyph on a light plate. Recolouring the *plate*
(rather than the glyph) keeps the mark readable at Dock and Spotlight sizes,
where a tinted glyph on white turns to mush.

Each pixel is remapped along a two-stop ramp built from the target colour:
luminance 0 lands on white, luminance 1 on the plate colour. Alpha is
preserved so the rounded corners and drop shadow survive.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: python3 -m pip install Pillow")

# Ten well-separated hues. Values track the macOS system palette so the set
# looks native next to other Dock icons.
PALETTE: dict[str, str] = {
    "blue": "#2E7CF6",
    "green": "#34C759",
    "purple": "#AF52DE",
    "orange": "#FF9500",
    "red": "#FF3B30",
    "teal": "#30B0C7",
    "pink": "#FF2D92",
    "yellow": "#FFCC00",
    "indigo": "#5856D6",
    "graphite": "#8E8E93",
}

# Sizes iconutil expects in a complete .iconset.
ICONSET_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def parse_hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {value!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def build_ramp(colour: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """Map luminance 0-255 onto a white-glyph -> coloured-plate ramp.

    The source art is a dark glyph on a light plate. Tinting it directly leaves
    the glyph almost black, which turns into an unreadable smudge on a dark Dock.
    Inverting the ramp puts a white glyph on the coloured plate instead, which is
    the usual macOS convention and holds contrast in both light and dark mode.
    """
    red, green, blue = colour
    glyph = (255.0, 255.0, 255.0)
    ramp = []
    for level in range(256):
        t = level / 255.0
        # Ease toward the plate colour so the glyph keeps clean, solid strokes
        # instead of a wide grey halo at the antialiased edges.
        eased = t ** 1.35
        ramp.append(
            (
                round(glyph[0] + (red - glyph[0]) * eased),
                round(glyph[1] + (green - glyph[1]) * eased),
                round(glyph[2] + (blue - glyph[2]) * eased),
            )
        )
    return ramp


def recolour(image: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    luminance = image.convert("L")
    ramp = build_ramp(colour)

    flat = luminance.load()
    out = Image.new("RGBA", image.size)
    pixels = out.load()
    width, height = image.size
    alpha_data = alpha.load()
    for y in range(height):
        for x in range(width):
            r, g, b = ramp[flat[x, y]]
            pixels[x, y] = (r, g, b, alpha_data[x, y])
    return out


def largest_source(iconset: Path) -> Image.Image:
    candidates = sorted(
        iconset.glob("*.png"), key=lambda p: p.stat().st_size, reverse=True
    )
    if not candidates:
        raise SystemExit(f"no PNGs extracted from the source icon in {iconset}")
    return Image.open(candidates[0]).convert("RGBA")


def build_variant(master: Image.Image, name: str, hex_colour: str, out_dir: Path) -> Path:
    colour = parse_hex(hex_colour)
    tinted = recolour(master, colour)

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / f"{name}.iconset"
        iconset.mkdir()
        for filename, size in ICONSET_SIZES:
            tinted.resize((size, size), Image.LANCZOS).save(iconset / filename)
        target = out_dir / f"multicodex-{name}.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(target)],
            check=True,
            capture_output=True,
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets" / "electron.icns",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets" / "icons",
    )
    parser.add_argument("--only", help="build a single colour by name")
    args = parser.parse_args()

    if not args.source.is_file():
        return print(f"source icon not found: {args.source}") or 1
    if not shutil.which("iconutil"):
        return print("iconutil not found (needs macOS)") or 1

    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp) / "source.iconset"
        subprocess.run(
            ["iconutil", "-c", "iconset", str(args.source), "-o", str(extracted)],
            check=True,
            capture_output=True,
        )
        master = largest_source(extracted)
        print(f"source master: {master.size[0]}x{master.size[1]}")

        wanted = {args.only: PALETTE[args.only]} if args.only else PALETTE
        for name, hex_colour in wanted.items():
            path = build_variant(master, name, hex_colour, args.out)
            print(f"  {name:9} {hex_colour}  ->  {path.name} ({path.stat().st_size:,} bytes)")

    print(f"\n{len(wanted)} icon(s) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
