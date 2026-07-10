#!/usr/bin/env python3
"""Generate standard gate icon PNGs without external image libs."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


OUT_DIR = Path(__file__).resolve().parent
SCALE = 4
WIDTH = 120
HEIGHT = 72
STROKE = 2.2
BLACK = (17, 24, 39, 255)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, rgba: bytearray) -> None:
    raw = bytearray()
    row_bytes = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * row_bytes:(y + 1) * row_bytes])
    payload = b"\x89PNG\r\n\x1a\n"
    payload += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    payload += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    payload += _chunk(b"IEND", b"")
    path.write_bytes(payload)


def new_canvas(width: int, height: int) -> bytearray:
    return bytearray(width * height * 4)


def blend_pixel(img: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    i = (y * width + x) * 4
    src_a = color[3] / 255.0
    dst_a = img[i + 3] / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    if out_a == 0:
        return
    for c in range(3):
        src = color[c] / 255.0
        dst = img[i + c] / 255.0
        img[i + c] = int(round(((src * src_a) + (dst * dst_a * (1.0 - src_a))) / out_a * 255))
    img[i + 3] = int(round(out_a * 255))


def draw_disc(img: bytearray, width: int, height: int, cx: float, cy: float, radius: float, color: tuple[int, int, int, int]) -> None:
    x0 = int(math.floor(cx - radius))
    x1 = int(math.ceil(cx + radius))
    y0 = int(math.floor(cy - radius))
    y1 = int(math.ceil(cy + radius))
    r2 = radius * radius
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                blend_pixel(img, width, height, x, y, color)


def clear_disc(img: bytearray, width: int, height: int, cx: float, cy: float, radius: float) -> None:
    x0 = int(math.floor(cx - radius))
    x1 = int(math.ceil(cx + radius))
    y0 = int(math.floor(cy - radius))
    y1 = int(math.ceil(cy + radius))
    r2 = radius * radius
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if x < 0 or y < 0 or x >= width or y >= height:
                continue
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                i = (y * width + x) * 4
                img[i:i + 4] = b"\x00\x00\x00\x00"


def draw_line(img: bytearray, width: int, height: int, a: tuple[float, float], b: tuple[float, float], stroke: float, color: tuple[int, int, int, int]) -> None:
    ax, ay = a
    bx, by = b
    steps = max(1, int(max(abs(bx - ax), abs(by - ay)) * 2))
    for i in range(steps + 1):
        t = i / steps
        draw_disc(img, width, height, ax + (bx - ax) * t, ay + (by - ay) * t, stroke / 2, color)


def cubic(p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], steps: int = 80) -> list[tuple[float, float]]:
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points


def draw_path(img: bytearray, width: int, height: int, points: list[tuple[float, float]], stroke: float, color: tuple[int, int, int, int]) -> None:
    for a, b in zip(points, points[1:]):
        draw_line(img, width, height, a, b, stroke, color)


def scaled(point: tuple[float, float]) -> tuple[float, float]:
    return (point[0] * SCALE, point[1] * SCALE)


def downsample(src: bytearray, width: int, height: int) -> bytearray:
    dst = bytearray((width // SCALE) * (height // SCALE) * 4)
    out_width = width // SCALE
    samples = SCALE * SCALE
    for y in range(0, height, SCALE):
        for x in range(0, width, SCALE):
            accum = [0, 0, 0, 0]
            for yy in range(SCALE):
                for xx in range(SCALE):
                    i = ((y + yy) * width + (x + xx)) * 4
                    for c in range(4):
                        accum[c] += src[i + c]
            j = ((y // SCALE) * out_width + (x // SCALE)) * 4
            for c in range(4):
                dst[j + c] = accum[c] // samples
    return dst


def draw_or_gate(extra_xor_curve: bool) -> bytearray:
    hw = WIDTH * SCALE
    hh = HEIGHT * SCALE
    img = new_canvas(hw, hh)
    stroke = STROKE * SCALE

    def s_path(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [scaled(p) for p in points]

    # Standard OR outline: concave input side, two convex output curves, and pin stubs.
    left = cubic((24, 8), (44, 20), (44, 52), (24, 64))
    top = cubic((24, 8), (58, 8), (88, 16), (108, 36))
    bottom = cubic((24, 64), (58, 64), (88, 56), (108, 36))
    if extra_xor_curve:
        xor_left = cubic((12, 9), (30, 21), (30, 51), (12, 63))
        draw_path(img, hw, hh, s_path(xor_left), stroke, BLACK)
    for path in (left, top, bottom):
        draw_path(img, hw, hh, s_path(path), stroke, BLACK)
    for a, b in [((0, 26), (34, 26)), ((0, 46), (34, 46)), ((108, 36), (120, 36))]:
        draw_line(img, hw, hh, scaled(a), scaled(b), stroke, BLACK)
    return downsample(img, hw, hh)


def draw_and_gate() -> bytearray:
    hw = WIDTH * SCALE
    hh = HEIGHT * SCALE
    img = new_canvas(hw, hh)
    stroke = STROKE * SCALE

    def s_path(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [scaled(p) for p in points]

    # Standard AND outline: flat input side and rounded output side.
    top = [(30, 12), (60, 12)]
    right = cubic((60, 12), (106, 12), (106, 60), (60, 60))
    bottom = [(60, 60), (30, 60), (30, 12)]
    draw_path(img, hw, hh, s_path(top), stroke, BLACK)
    draw_path(img, hw, hh, s_path(right), stroke, BLACK)
    draw_path(img, hw, hh, s_path(bottom), stroke, BLACK)
    for a, b in [((0, 26), (30, 26)), ((0, 46), (30, 46)), ((94, 36), (120, 36))]:
        draw_line(img, hw, hh, scaled(a), scaled(b), stroke, BLACK)
    return downsample(img, hw, hh)


def draw_dff_with_reset() -> bytearray:
    hw = WIDTH * SCALE
    hh = HEIGHT * SCALE
    img = new_canvas(hw, hh)
    stroke = STROKE * SCALE

    # Register body.
    body_left, body_top = 30, 16
    body_right, body_bottom = 92, 64
    corners = [
        ((body_left, body_top), (body_right, body_top)),
        ((body_right, body_top), (body_right, body_bottom)),
        ((body_right, body_bottom), (body_left, body_bottom)),
        ((body_left, body_bottom), (body_left, body_top)),
    ]
    for a, b in corners:
        draw_line(img, hw, hh, scaled(a), scaled(b), stroke, BLACK)

    # D input, Q output, active-low reset pin, and clock edge triangle.
    for a, b in [((0, 28), (30, 28)), ((92, 28), (120, 28)), ((62, 0), (62, 8))]:
        draw_line(img, hw, hh, scaled(a), scaled(b), stroke, BLACK)
    draw_disc(img, hw, hh, 62 * SCALE, 12 * SCALE, 4.2 * SCALE, BLACK)
    clear_disc(img, hw, hh, 62 * SCALE, 12 * SCALE, 2.1 * SCALE)

    draw_line(img, hw, hh, scaled((0, 52)), scaled((22, 52)), stroke, BLACK)
    for a, b in [((22, 46), (30, 52)), ((30, 52), (22, 58)), ((22, 58), (22, 46))]:
        draw_line(img, hw, hh, scaled(a), scaled(b), stroke, BLACK)
    return downsample(img, hw, hh)


def main() -> None:
    write_png(OUT_DIR / "and.png", WIDTH, HEIGHT, draw_and_gate())
    write_png(OUT_DIR / "dff_r.png", WIDTH, HEIGHT, draw_dff_with_reset())
    write_png(OUT_DIR / "or.png", WIDTH, HEIGHT, draw_or_gate(extra_xor_curve=False))
    write_png(OUT_DIR / "xor.png", WIDTH, HEIGHT, draw_or_gate(extra_xor_curve=True))


if __name__ == "__main__":
    main()
