"""Versioned read-only, paged external GAM data; never executable code."""

import hashlib
import struct
import zlib

PAGE_SIZE = 4096
MAX_SIZE = 32 * 1024 * 1024
HEADER = struct.Struct("<8sIIIII32sI")


def pack_resources(game: bytes) -> tuple[str, bytes]:
    if not 0 < len(game) <= MAX_SIZE:
        raise ValueError("外置资源支持最大 32 MiB 的 GAM。")
    digest = hashlib.sha256(game).digest()
    pages = (len(game) + PAGE_SIZE - 1) // PAGE_SIZE
    checksums = b"".join(
        struct.pack("<I", zlib.crc32(game[i : i + PAGE_SIZE]))
        for i in range(0, len(game), PAGE_SIZE)
    )
    header = HEADER.pack(
        b"A9288RES",
        1,
        PAGE_SIZE,
        len(game),
        pages,
        HEADER.size + len(checksums),
        digest,
        zlib.crc32(checksums),
    )
    # 8.3 ASCII name: no reliance on the firmware's long-name/GBK aliases.
    return "R" + digest.hex()[:7].upper() + ".RES", header + checksums + game


def c_resource_config(name: str, header: bytes) -> str:
    path = ("a:\\系统\\数据\\" + name).encode("gbk")
    literal = "".join(f"\\x{b:02x}" for b in path)
    values = ",".join(f"0x{b:02x}" for b in header[: HEADER.size])
    return (
        f"#define C6502_EXTERNAL_RESOURCES 1\n"
        f'#define C6502_RESOURCE_PATH "{literal}"\n'
        f"#define C6502_RESOURCE_HEADER {{{values}}}\n"
    )
