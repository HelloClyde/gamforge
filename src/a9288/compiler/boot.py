"""Offline reference boot exporter; this helper is never linked into a KF2."""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from a9288.paths import DATA, DEPENDENCIES, WORK

DEFAULT_ROM8 = Path(os.environ.get("A9288_ROM8", DEPENDENCIES / "roms/8.BIN"))
DEFAULT_ROME = Path(os.environ.get("A9288_ROME", DEPENDENCIES / "roms/E.BIN"))
BOOT_DEFINES = (
    "GAM4980_ENABLE_AOT",
    "GAM4980_ENABLE_NATIVE_TRACE_AOT",
    "GAM4980_ENABLE_FIRMWARE_HLE",
    "GAM4980_FIRMWARE_HLE_MASK=1023",
    "GAM4980_ENABLE_AGGRESSIVE_REGION_HLE",
    "GAM4980_ENABLE_GAME_LOAD_AOT",
    "GAM4980_ENABLE_IRAM_EXEC_ENGINE",
    "GAM4980_IRAM_EXEC_NATIVE_TEST",
)


def bundled_helper():
    return DATA / "bin" / ("native-boot.exe" if os.name == "nt" else "native-boot")


def build_helper(output: Path, cc: str = "gcc"):
    source = DATA / "boot_reference"
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            cc,
            "-O2",
            "-std=gnu11",
            *(["-static"] if os.name == "nt" else []),
            *("-D" + value for value in BOOT_DEFINES),
            "-I",
            str(source),
            str(source / "export_native_boot_snapshot.c"),
            str(source / "gam4980_core.c"),
            "-o",
            str(output),
        ],
        check=True,
    )


def export_snapshot(
    game: Path, output: Path, rom8: Path = DEFAULT_ROM8, rome: Path = DEFAULT_ROME, cc: str = "gcc"
):
    for rom in (rom8, rome):
        if not rom.is_file() or rom.stat().st_size != 2 * 1024 * 1024:
            raise ValueError(f"需要用户提供的 2 MiB 固件文件：{rom}")
    executable = bundled_helper()
    if not executable.is_file():
        digest = hashlib.sha256()
        for path in sorted((DATA / "boot_reference").iterdir()):
            digest.update(path.read_bytes())
        executable = WORK / "helpers" / digest.hexdigest()[:16] / bundled_helper().name
        if not executable.is_file():
            build_helper(executable, cc)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Only ASCII relative names reach the narrow C fopen; Unicode parent paths
    # are handled by Python/CreateProcess, including Chinese Windows user names.
    with tempfile.TemporaryDirectory(prefix="a9288-boot-") as folder:
        stage = Path(folder)
        for src, name in ((game, "game.gam"), (rom8, "8.BIN"), (rome, "E.BIN")):
            shutil.copyfile(src, stage / name)
        subprocess.run(
            [str(executable), "8.BIN", "E.BIN", "game.gam", "boot.bin"], cwd=stage, check=True
        )
        data = (stage / "boot.bin").read_bytes()
        if data[:8] != b"C65BOOT\0":
            raise ValueError("Invalid reference boot state")
        shutil.copyfile(stage / "boot.bin", output)
