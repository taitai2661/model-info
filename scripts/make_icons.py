#!/usr/bin/env python3
"""Regenerate the raster app icons from the favicon design.

The SVG (`favicon.svg`) is the source of truth and is used directly by browsers.
This script renders the same design to PNG for platforms that need a raster
image (`apple-touch-icon.png`, PWA manifest icons). It has no third-party
dependencies: shapes are rasterised with a signed-distance-field coverage so the
edges stay smooth, and the PNG is written with the standard library only.

Usage:
    python3 scripts/make_icons.py [--out DIR]
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

# -- design (512x512 design space, matching favicon.svg) --------------------

DESIGN = 512.0
CORNER_RADIUS = 116.0
GRADIENT_START = (0x3B, 0x82, 0xF6)   # #3b82f6
GRADIENT_END = (0x43, 0x38, 0xCA)     # #4338ca
BARS = ((120, 132, 204, 58, 29), (120, 227, 156, 58, 29), (120, 322, 108, 58, 29))
DOT = (360.0, 161.0, 33.0, (0xBF, 0xDB, 0xFE))  # #bfdbfe
ICON_SIZES = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}


def _rounded_rect_distance(px, py, x, y, w, h, r):
    cx, cy = x + w / 2.0, y + h / 2.0
    qx = abs(px - cx) - (w / 2.0 - r)
    qy = abs(py - cy) - (h / 2.0 - r)
    outside = (max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) ** 0.5
    return min(max(qx, qy), 0.0) + outside - r


def _circle_distance(px, py, cx, cy, r):
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 - r


def _coverage(distance):
    return min(max(0.5 - distance, 0.0), 1.0)


def _over(dst, src, alpha):
    """Composite src (RGB tuple) over dst (RGB tuple) with coverage alpha."""
    if alpha <= 0.0:
        return dst
    if alpha >= 1.0:
        return src
    return tuple(round(s * alpha + d * (1.0 - alpha)) for s, d in zip(src, dst))


def render(size: int) -> bytes:
    scale = DESIGN / size
    out = bytearray()
    for j in range(size):
        for i in range(size):
            px = (i + 0.5) * scale
            py = (j + 0.5) * scale

            # Rounded-square background with a diagonal gradient.
            t = (px / DESIGN + py / DESIGN) / 2.0
            bg = tuple(round(a + (b - a) * t) for a, b in zip(GRADIENT_START, GRADIENT_END))
            r, g, b = bg
            a = _coverage(_rounded_rect_distance(px, py, 0, 0, DESIGN, DESIGN, CORNER_RADIUS))

            white = (255, 255, 255)
            for x, y, w, h, rad in BARS:
                cov = _coverage(_rounded_rect_distance(px, py, x, y, w, h, rad))
                if cov > 0:
                    r, g, b = _over((r, g, b), white, cov)
                    a = a + (1.0 - a) * cov

            cx, cy, dot_r, dot_color = DOT
            cov = _coverage(_circle_distance(px, py, cx, cy, dot_r))
            if cov > 0:
                r, g, b = _over((r, g, b), dot_color, cov)
                a = a + (1.0 - a) * cov

            out += bytes((r, g, b, round(a * 255)))
    return bytes(out)


def write_png(path: Path, size: int, pixels: bytes) -> None:
    stride = size * 4
    raw = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render the Model Info icons to PNG")
    parser.add_argument("--out", default=None, help="output directory (default: repo root)")
    args = parser.parse_args(argv)
    root = Path(args.out) if args.out else Path(__file__).resolve().parent.parent

    for name, size in ICON_SIZES.items():
        write_png(root / name, size, render(size))
        print(f"wrote {root / name} ({size}x{size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
