"""9288S / TSW600 D300 executable, checked against the SDK's Apmk output.

The executable retains the GNU33 load address/ABI, but has two 128-byte
headers and a native 32x32 two-frame LICON, not KF2 icon descriptors.
"""

from __future__ import annotations

import struct
from pathlib import Path

from a9288.compiler.kf2 import APP_MAX_PAYLOAD_SIZE, read_icon
from a9288.targets import target_profile

ICON_DESCRIPTOR = bytes.fromhex("10 00 10 00 00 02 00 00 20 00 40 00 00 02 00 00")
PROGRAM_OFFSET = 0x310


def pack_d300(payload: bytes, *, app_name: bytes, icon_root: Path, target: str = "9288s") -> bytes:
    profile = target_profile(target)
    if profile.executable_format != "D300":
        raise ValueError(f"{profile.name} requires {profile.executable_format}, not D300")
    if not app_name or len(app_name) > 15 or b"\0" in app_name:
        raise ValueError("D300 name must contain 1-15 GBK bytes and no embedded NUL")
    if not payload or len(payload) > APP_MAX_PAYLOAD_SIZE:
        raise ValueError("D300 payload must fit the 1 MiB application RAM window")
    # Apmk pads the program to a word boundary and includes that in both sizes.
    payload += b"\0" * (-len(payload) & 3)
    icon = ICON_DESCRIPTOR + b"".join(
        read_icon(icon_root / name, 32, 32)[12:] for name in ("ico1.bin", "ico2.bin")
    )
    primary = bytearray(0x80)
    primary[:4] = b"D300"
    struct.pack_into("<II", primary, 4, 0x80, PROGRAM_OFFSET + len(payload))
    primary[0x0C:0x14] = profile.category.encode("gbk").ljust(8, b"\0")
    struct.pack_into("<I", primary, 0x14, 0x100)  # minimum OS version
    struct.pack_into("<I", primary, 0x1C, 1)  # EXE file type
    primary[0x20:0x40] = "OS版本太低".encode("gbk").ljust(32, b"\0")
    primary[0x40:0x50] = b"GAMForge".ljust(16, b"\0")  # copyright, NOT title
    struct.pack_into("<II", primary, 0x50, profile.d300_magic, 0x100)
    secondary = bytearray(0x80)
    secondary[:4] = b"EXE\0"
    struct.pack_into(
        "<7I", secondary, 4, 0x80, 0x100, len(icon), 0, 0, PROGRAM_OFFSET, len(payload)
    )
    secondary[0x30:0x50] = app_name.ljust(32, b"\0")
    return bytes(primary + secondary) + icon + payload
