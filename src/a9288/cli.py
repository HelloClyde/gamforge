#!/usr/bin/env python3
"""PC-recompile a C6502 GAM into a standalone native 9288 KF2, no interpreter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from a9288.app_options import compiler_lock, default_app_name, encode_app_name, inspect_game
from a9288.compiler.boot import DEFAULT_ROM8, DEFAULT_ROME
from a9288.paths import DEPENDENCIES, WORK, child_environment, task_command

DEFAULT_SDK = Path(os.environ.get("A9288_SDK", DEPENDENCIES / "sdk9288"))
DEFAULT_TOOLCHAIN = Path(os.environ.get("A9288_TOOLCHAIN", DEPENDENCIES / "toolchain"))
MAX_KF2_BYTES = 1024 * 1024


def publish_file(source: Path, destination: Path) -> None:
    """Replace only completed artifacts; a failed compile keeps the old EXE."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="." + destination.name + ".", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def convert(args) -> None:
    game = args.game.resolve()
    inspect_game(game)
    name = args.app_name if args.app_name is not None else default_app_name(game.stem)
    encode_app_name(name)
    sdk = args.sdk.resolve()
    if not sdk.is_dir():
        raise ValueError(f"9288 SDK not found: {sdk}")
    output = args.output.resolve() if args.output else Path.cwd() / f"{game.stem}-NATIVE.exe"
    if output.suffix.lower() != ".exe":
        raise ValueError("输出文件必须以 .exe 结尾。")
    if output == game or (args.icon and output == args.icon.resolve()):
        raise ValueError("输出不能覆盖输入游戏或图标。")
    work = args.work_dir.resolve()
    staged = work / "native-result" / "program.exe"
    command = task_command(
        "compiler.build",
        str(game),
        "--sdk",
        str(sdk),
        "--toolchain",
        str(args.toolchain.resolve()),
        "--output",
        str(staged),
        "--app-name",
        name,
        "--work-dir",
        str(work),
        "--rom8",
        str(args.rom8.resolve()),
        "--rome",
        str(args.rome.resolve()),
    )
    if args.icon:
        command += ["--icon", str(args.icon.resolve())]
    if getattr(args, "profile_other", False):
        command.append("--profile-other")
    print("+", " ".join(command), flush=True)
    subprocess.run(command, env=child_environment(), check=True)
    size = staged.stat().st_size
    if size >= MAX_KF2_BYTES:
        raise ValueError(f"生成 EXE 为 {size} 字节，超过当前 1 MiB 限制；未替换原输出文件。")
    digest = hashlib.sha256(staged.read_bytes()).hexdigest()
    report = json.loads((work / "c6502-s1c33-direct/report.json").read_text(encoding="utf-8"))
    report.update(
        {
            "format": "c6502-direct-s1c33-kf2-v1",
            "output_kf2": str(output),
            "output_kf2_bytes": size,
            "output_kf2_sha256": digest,
            "app_name": name,
            "app_name_encoding": "gbk",
            "app_category": "entertainment",
            "icon_source": str(args.icon.resolve()) if args.icon else "bundled-default",
            "standalone_link_complete": True,
            "standalone_game_resources": True,
            "requires_original_gam": False,
            "runtime_opcode_dispatcher": False,
            "runtime_guest_cycle_scheduler": False,
            "runtime_interpreter_fallback": False,
            "bridge_contract": "explicit-native-case-required",
            "host_sdk_abi": "9288-gnu33-r6-r9-return-r4-reserved-r15",
            "profile_other": bool(getattr(args, "profile_other", False)),
            "output_elf": str(output.with_suffix(".elf")),
            "output_map": str(output.with_suffix(".map")),
            "sdk": str(sdk),
        }
    )
    staged_report = staged.with_suffix(".report.json")
    staged_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("[GAM9288_STAGE] verify|校验体积并保存转换结果", flush=True)
    for suffix in (".elf", ".map", ".report.json", ".exe"):
        publish_file(staged.with_suffix(suffix), output.with_suffix(suffix))
    if getattr(args, "profile_other", False):
        publish_file(
            staged.with_suffix(".profile-symbols.json"), output.with_suffix(".profile-symbols.json")
        )
    print(f"KF2: {output} ({size} bytes)\nSHA256: {digest}", flush=True)
    print(f"report: {output.with_suffix('.report.json')}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path, help="input .gam file")
    parser.add_argument("--sdk", type=Path, default=DEFAULT_SDK)
    parser.add_argument("--toolchain", type=Path, default=DEFAULT_TOOLCHAIN)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--app-name", help="9288 桌面和窗口名称，最多 15 个 GBK 字节")
    parser.add_argument("--icon", type=Path, help="PNG/JPEG/BMP/ICO 图片，自动转换四灰阶图标")
    parser.add_argument(
        "--profile-other",
        action="store_true",
        help="添加原生调用区间及运行库抽样耗时日志（诊断版）",
    )
    parser.add_argument("--work-dir", type=Path, default=WORK / "cli")
    parser.add_argument("--rom8", type=Path, default=DEFAULT_ROM8)
    parser.add_argument("--rome", type=Path, default=DEFAULT_ROME)
    args = parser.parse_args()
    try:
        with compiler_lock(WORK / "native-compiler.lock"):
            convert(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"转换失败：{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
