"""Assemble explicitly authorized offline dependencies; never include games.

Normal public CI still builds the light package. Maintainers build the full
bundle from supplied dependencies and upload it after an isolated conversion.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from a9288 import __version__
from a9288.compiler.build import verify_9288_abi

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("clang", "ld.lld", "llvm-objcopy", "llvm-readelf")


def isolated_environment(work):
    compiler_overrides = {
        "CC",
        "CXX",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "INCLUDE",
        "LIB",
        "LIBPATH",
    }
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(("A9288_", "PYTHON", "CONDA"))
        and k.upper() not in compiler_overrides
    }
    env["LOCALAPPDATA"] = str(work / "profile")
    env["A9288_WORKSPACE"] = str(work / "work")
    env["PATH"] = str(Path(env.get("SYSTEMROOT") or env["SystemRoot"]) / "System32")
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-dir", type=Path, default=ROOT / "dist/A9288-Translator")
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--rom8", type=Path, required=True)
    parser.add_argument("--rome", type=Path, required=True)
    parser.add_argument(
        "--vc-runtime",
        type=Path,
        required=True,
        help="x64 redistributable CRT DLL directory, not System32",
    )
    parser.add_argument("--authorized-redistribution", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / f"a9288-translator-{__version__}-full-windows-x64.zip",
    )
    args = parser.parse_args()
    if not args.authorized_redistribution:
        parser.error("Explicit SDK/firmware redistribution authorization is required")
    if os.name != "nt":
        parser.error("Build the Windows full bundle on Windows")
    for p in (args.rom8, args.rome):
        if p.stat().st_size != 2 * 1024 * 1024:
            parser.error("Expected 2 MiB A-series firmware images")
    headers = args.sdk / "Down_Include"
    if not (headers / "Dsys.h").is_file():
        parser.error("9288 SDK Down_Include/Dsys.h is required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="full-bundle-", dir=args.output.parent) as temporary:
        work = Path(temporary)
        folder = work / "A9288-Translator"
        shutil.copytree(args.portable_dir, folder)
        deps = folder / "dependencies"
        if deps.exists():
            parser.error("Input must be a clean light package without dependencies")
        # Copy only headers actually needed by this compiler, not SDK games,
        # historical EXEs or unrelated tools from the developer's directory.
        for header in headers.rglob("*.h"):
            dest = deps / "sdk9288/Down_Include" / header.relative_to(headers)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(header, dest)
        if (args.sdk / "readme.txt").is_file():
            shutil.copyfile(args.sdk / "readme.txt", deps / "sdk9288/readme.txt")
        (deps / "roms").mkdir()
        shutil.copyfile(args.rom8, deps / "roms/8.BIN")
        shutil.copyfile(args.rome, deps / "roms/E.BIN")
        tools = deps / "toolchain/bin"
        tools.mkdir(parents=True)
        for name in TOOLS:
            shutil.copyfile(args.toolchain / "bin" / (name + ".exe"), tools / (name + ".exe"))
        required = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")
        for name in required:
            if not (args.vc_runtime / name).is_file():
                parser.error(f"Redistributable CRT missing {name}")
        for dll in args.vc_runtime.glob("*.dll"):
            shutil.copyfile(dll, tools / dll.name)
        clang_lib = args.toolchain / "lib/clang"
        if clang_lib.is_dir():
            for include in clang_lib.glob("*/include"):
                shutil.copytree(
                    include, deps / "toolchain/lib/clang" / include.parent.name / "include"
                )
        for name in ("LLVM-LICENSE.TXT", "9288-gnu33-abi.patch", "manifest.json"):
            shutil.copyfile(ROOT / "toolchain" / name, deps / "toolchain" / name)
        verify_9288_abi(str(tools / "clang.exe"))
        env = isolated_environment(work)
        report = json.loads(
            subprocess.check_output(
                [str(folder / "A9288-CLI.exe"), "--self-test"], env=env, cwd=work, encoding="utf-8"
            )
        )
        assert report["self_test"] == "PASS" and report["version"] == __version__, report
        for path in report["dependencies"].values():
            p = Path(path).resolve()
            assert p.is_relative_to(deps.resolve()) and p.exists(), report
        files = sorted(p for p in folder.rglob("*") if p.is_file())
        assert not [p for p in files if p.suffix.lower() in (".gam", ".res", ".sav", ".rom")]
        metadata = {
            "version": __version__,
            "edition": "full",
            "sdk_firmware_redistribution_authorized": True,
            "sdk_scope": "9288 Down_Include headers",
            "toolchain_version": subprocess.check_output(
                [str(tools / "clang.exe"), "--version"], env=env, text=True
            ).splitlines()[0],
            "minimum_os": "Windows 10 x64",
            "games_included": False,
            "dependencies": {
                p.relative_to(deps).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in files
                if p.is_relative_to(deps)
            },
        }
        (folder / "FULL-BUNDLE.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (folder / "开始使用.txt").write_text(
            "全套离线版：完整解压后运行 A9288-Converter.exe，选择自己的 GAM 即可转换。\n无需安装 Python、SDK、编译器或手工填写依赖路径。\n请保留 dependencies 和 _internal 目录，不能只复制单个 EXE。\nEXE 放 A:\\系统\\程序；外置模式 RES 放 A:\\系统\\数据。\n需要 Windows 10/11 x64；不含游戏，不保证任意 GAM 兼容。\n",
            encoding="utf-8",
        )
        manifest = {
            p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p.name != "MANIFEST.sha256.json"
        }
        (folder / "MANIFEST.sha256.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        staged = work / "full.zip"
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for p in sorted(folder.rglob("*")):
                if p.is_file():
                    z.write(p, Path(folder.name) / p.relative_to(folder))
        os.replace(staged, args.output)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".zip.sha256").write_text(
        digest + "  " + args.output.name + "\n", encoding="ascii"
    )
    print(f"Full offline bundle: {args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
