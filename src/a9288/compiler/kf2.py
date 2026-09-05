from __future__ import annotations

import shutil
import struct
from pathlib import Path

from a9288.paths import DATA

PROJECT_ROOT = DATA

ICON_ROOT = DATA / "icons"

MAGIC0 = 0x0032464B

MAGIC1 = 0x19760212

HEADER_SIZE = 0x30

MACHINE_9288 = 1

APP_MODULE = 8

APP_NAME = b"GAM4980"

APP_LOAD_ADDRESS = 0x02700000

APP_RAM_END = 0x02800000

APP_MAX_PAYLOAD_SIZE = APP_RAM_END - APP_LOAD_ADDRESS


def write_sdk_header(path: Path, data: bytes) -> None:
    lines = []
    for line in data.splitlines(keepends=True):
        if line.lstrip().startswith(b"#include"):
            line = line.replace(b"\\", b"/")
        lines.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(lines))


def prepare_sdk_headers(sdk: Path, destination: Path) -> None:
    source = sdk / "Down_Include"
    if not source.is_dir():
        raise SystemExit(f"9288 SDK headers not found: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    for header in source.rglob("*.h"):
        relative = header.relative_to(source)
        data = header.read_bytes()
        variants = {
            relative,
            Path(*(part.lower() for part in relative.parts)),
            Path(*(part.lower() for part in relative.parts[:-1]), relative.name),
        }
        for variant in variants:
            write_sdk_header(destination / variant, data)


def find_tool(toolchain: Path, name: str) -> str:
    candidates = (
        toolchain / name,
        toolchain / f"{name}.exe",
        toolchain / "bin" / name,
        toolchain / "bin" / f"{name}.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(f"missing S1C33 tool: {name}; searched under {toolchain}")


def read_map_symbol(map_path: Path, name: str) -> int:
    suffix = f" {name} = ."
    for line in map_path.read_text(encoding="utf-8").splitlines():
        if line.endswith(suffix):
            try:
                return int(line.split()[0], 16)
            except (IndexError, ValueError) as exc:
                raise SystemExit(f"invalid {name} entry in {map_path}") from exc
    raise SystemExit(f"missing {name} in linker map: {map_path}")


def read_icon(path: Path, width: int, height: int) -> bytes:
    if not path.is_file():
        raise SystemExit(f"missing GAM4980 icon: {path}; run tools/convert_9288_icon.py")
    data = path.read_bytes()
    expected_size = 12 + width * height * 2 // 8
    if len(data) != expected_size:
        raise SystemExit(
            f"invalid 9288 icon size: {path} has {len(data)} bytes, expected {expected_size}"
        )
    icon_width, icon_height, bpp, reserved0, reserved1, reserved2 = struct.unpack_from(
        "<HHHHHH", data
    )
    if (icon_width, icon_height, bpp, reserved0, reserved1, reserved2) != (
        width,
        height,
        2,
        0,
        0,
        0,
    ):
        raise SystemExit(f"invalid 9288 icon header: {path}")
    return data


def pack_kf2(payload: bytes, *, app_name: bytes = APP_NAME, icon_root: Path | None = None) -> bytes:
    if len(payload) > APP_MAX_PAYLOAD_SIZE:
        raise SystemExit(
            "9288 KF2 payload is too large for the application RAM window: "
            f"{len(payload)} bytes, maximum {APP_MAX_PAYLOAD_SIZE}"
        )
    if not app_name or len(app_name) > 15 or b"\0" in app_name:
        raise ValueError("KF2 name must contain 1-15 bytes and no embedded NUL")
    icon_root = ICON_ROOT if icon_root is None else icon_root
    icon1 = read_icon(icon_root / "ico1.bin", 40, 40)
    icon2 = read_icon(icon_root / "ico2.bin", 16, 16)
    code_offset = HEADER_SIZE + len(icon1) + len(icon2)
    total_size = code_offset + len(payload)
    name = app_name.ljust(16, b"\0")
    header = struct.pack(
        "<IIHH16sIIIII",
        MAGIC0,
        MAGIC1,
        MACHINE_9288,
        APP_MODULE,
        name,
        code_offset,
        HEADER_SIZE,
        len(icon1),
        len(icon2),
        total_size,
    )
    if len(header) != HEADER_SIZE:
        raise AssertionError(f"KF2 header is {len(header)} bytes")
    return header + icon1 + icon2 + payload
