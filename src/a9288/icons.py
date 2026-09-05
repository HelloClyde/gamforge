from __future__ import annotations

import struct
from pathlib import Path


def decode_icon(path: Path, width: int, height: int) -> list[int]:
    data = path.read_bytes()
    expected_size = 12 + width * height * 2 // 8
    if len(data) != expected_size:
        raise ValueError(f"invalid 9288 frame resource size: {path}")
    if struct.unpack_from("<HHHHHH", data) != (width, height, 2, 0, 0, 0):
        raise ValueError(f"invalid 9288 frame resource header: {path}")

    pixels: list[int] = []
    for value in data[12:]:
        pixels.extend(((value >> 6) & 3, (value >> 4) & 3, (value >> 2) & 3, value & 3))
    return pixels


def encode_icon(width: int, height: int, pixels: list[int]) -> bytes:
    if width % 4:
        raise ValueError("9288 2-bpp icon width must be divisible by four")
    if len(pixels) != width * height:
        raise ValueError("pixel count does not match icon dimensions")

    payload = bytearray()
    for offset in range(0, len(pixels), 4):
        p0, p1, p2, p3 = pixels[offset : offset + 4]
        payload.append((p0 << 6) | (p1 << 4) | (p2 << 2) | p3)
    header = struct.pack("<HHHHHH", width, height, 2, 0, 0, 0)
    return header + payload
