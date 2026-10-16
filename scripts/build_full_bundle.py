"""Assemble explicitly authorized offline dependencies; never include games.

Normal public CI still builds the light package. Maintainers build the full
bundle from supplied dependencies and upload it after an isolated conversion.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from a9288 import __version__
from a9288.compiler.build import verify_9288_abi

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("clang", "ld.lld", "llvm-objcopy", "llvm-readelf")


def isolated_environment(work, target_platform="windows"):
    if target_platform == "macos":
        from build_macos import isolated_mac_environment

        return isolated_mac_environment(work)
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
        if not k.upper().startswith(("A9288_", "A9288T_", "A9288S_", "ATSW600_", "PYTHON", "CONDA"))
        and k.upper() not in compiler_overrides
    }
    env["LOCALAPPDATA"] = str(work / "profile")
    env["A9288_WORKSPACE"] = str(work / "work")
    env["PATH"] = str(Path(env.get("SYSTEMROOT") or env["SystemRoot"]) / "System32")
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portable-dir", type=Path, default=ROOT / "dist/GAMForge")
    parser.add_argument(
        "--platform",
        choices=("windows", "macos"),
        default="macos" if sys.platform == "darwin" else "windows",
    )
    parser.add_argument("--architecture", choices=("arm64", "x86_64"))
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument(
        "--sdk9288t", type=Path, help="Optional authorized 9288T SDK root (include/)"
    )
    parser.add_argument(
        "--sdk9288s",
        type=Path,
        help="Optional authorized 9288S/TSW600 shared SDK root (Down_Include/)",
    )
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--rom8", type=Path, required=True)
    parser.add_argument("--rome", type=Path, required=True)
    parser.add_argument(
        "--vc-runtime",
        type=Path,
        help="Required on Windows only: x64 redistributable CRT DLL directory, not System32",
    )
    parser.add_argument("--authorized-redistribution", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
    )
    args = parser.parse_args()
    if not args.authorized_redistribution:
        parser.error("Explicit SDK/firmware redistribution authorization is required")
    macos = args.platform == "macos"
    architecture = args.architecture or (platform.machine() if macos else "x86_64")
    if macos:
        from build_macos import (
            archive_tree,
            audit_payload,
            frozen_self_test,
            mac_layout,
            require_native_host,
            sign_app,
            verify_minimum_os,
            verify_native,
            verify_system_libraries,
            write_manifest,
        )

        try:
            require_native_host(architecture)
        except ValueError as error:
            parser.error(str(error))
        if args.vc_runtime:
            parser.error("macOS packages must use native tools, not Windows VC runtime")
    elif os.name != "nt" or architecture != "x86_64":
        parser.error("Build the Windows x64 full bundle on Windows")
    elif not args.vc_runtime:
        parser.error("--vc-runtime is required for the Windows full bundle")
    args.output = args.output or ROOT / "dist" / (
        f"gamforge-{__version__}-full-macos-{architecture}.zip"
        if macos
        else f"gamforge-{__version__}-full-windows-x64.zip"
    )
    for p in (args.rom8, args.rome):
        if p.stat().st_size != 2 * 1024 * 1024:
            parser.error("Expected 2 MiB A-series firmware images")
    headers = args.sdk / "Down_Include"
    if not (headers / "Dsys.h").is_file():
        parser.error("9288 SDK Down_Include/Dsys.h is required")
    if args.sdk9288t and not (args.sdk9288t / "include/Dsys.h").is_file():
        parser.error("9288T SDK include/Dsys.h is required")
    if args.sdk9288s and not (args.sdk9288s / "Down_Include/Dsys.h").is_file():
        parser.error("9288S SDK Down_Include/Dsys.h is required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="full-bundle-", dir=args.output.parent) as temporary:
        work = Path(temporary)
        folder = work / "GAMForge"
        shutil.copytree(args.portable_dir, folder, symlinks=macos)
        if macos:
            # Validate confinement before writing through any bundle directory.
            # In particular Resources must not be an external/dangling symlink.
            audit_payload(folder)
        deps = mac_layout(folder)[2] if macos else folder / "dependencies"
        if deps.exists():
            parser.error("Input must be a clean light package without dependencies")
        if macos:
            metadata_file = folder / "MACOS-BUNDLE.json"
            light_metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            if light_metadata.get("architecture") != architecture:
                parser.error("Light package and requested native toolchain architectures differ")
            if light_metadata.get("version") != __version__:
                parser.error("Light package version does not match this source checkout")
        # Copy only headers actually needed by this compiler, not SDK games,
        # historical EXEs or unrelated tools from the developer's directory.
        for header in headers.rglob("*.h"):
            dest = deps / "sdk9288/Down_Include" / header.relative_to(headers)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(header, dest)
        if (args.sdk / "readme.txt").is_file():
            shutil.copyfile(args.sdk / "readme.txt", deps / "sdk9288/readme.txt")
        if args.sdk9288t:
            t_headers = args.sdk9288t / "include"
            for header in t_headers.rglob("*.h"):
                dest = deps / "sdk9288t/include" / header.relative_to(t_headers)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(header, dest)
        if args.sdk9288s:
            s_headers = args.sdk9288s / "Down_Include"
            for header in s_headers.rglob("*.h"):
                dest = deps / "sdk9288s/Down_Include" / header.relative_to(s_headers)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(header, dest)
            if (args.sdk9288s / "readme.txt").is_file():
                shutil.copyfile(args.sdk9288s / "readme.txt", deps / "sdk9288s/readme.txt")
        (deps / "roms").mkdir()
        shutil.copyfile(args.rom8, deps / "roms/8.BIN")
        shutil.copyfile(args.rome, deps / "roms/E.BIN")
        tools = deps / "toolchain/bin"
        tools.mkdir(parents=True)
        suffix = "" if macos else ".exe"
        for name in TOOLS:
            source = args.toolchain / "bin" / (name + suffix)
            destination = tools / (name + suffix)
            if macos:
                verify_native(source, architecture)
                verify_system_libraries(source)
                shutil.copy2(source, destination)
                destination.chmod(0o755)
                subprocess.run(["codesign", "--force", "--sign", "-", str(destination)], check=True)
            else:
                shutil.copyfile(source, destination)
        if not macos:
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
        if macos:
            # Input hashes predate ad-hoc re-signing above; FULL-BUNDLE.json
            # separately records the final installed bytes, including signatures.
            shutil.copyfile(
                args.toolchain / "manifest.json",
                deps / "toolchain/BUILD-INPUT-MANIFEST.json",
            )
        compiler = tools / ("clang" + suffix)
        verify_9288_abi(str(compiler))
        env = isolated_environment(work, args.platform)
        if macos:
            verify_minimum_os(folder, light_metadata["minimum_os"].removeprefix("macOS "))
            sign_app(mac_layout(folder)[0])
            report = frozen_self_test(folder, work)
        else:
            report = json.loads(
                subprocess.check_output(
                    [str(folder / "GAMForge-CLI.exe"), "--self-test"],
                    env=env,
                    cwd=work,
                    encoding="utf-8",
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
            "sdk_scope": "9288 Down_Include headers"
            + (" and 9288T include headers" if args.sdk9288t else "")
            + (" and shared 9288S/TSW600 Down_Include headers" if args.sdk9288s else ""),
            "targets": ["9288"]
            + (["9288t"] if args.sdk9288t else [])
            + (["9288s", "tsw600"] if args.sdk9288s else []),
            "sdk9288t_included": bool(args.sdk9288t),
            "sdk9288s_included": bool(args.sdk9288s),
            "tsw600_shared_sdk_included": bool(args.sdk9288s),
            "toolchain_version": subprocess.check_output(
                [str(compiler), "--version"], env=env, text=True
            ).splitlines()[0],
            "minimum_os": light_metadata["minimum_os"] if macos else "Windows 10 x64",
            "games_included": False,
            "dependencies": {
                p.relative_to(deps).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in files
                if p.is_relative_to(deps)
            },
        }
        if macos:
            metadata.update(
                platform="macos", architecture=architecture, signing="ad-hoc", notarized=False
            )
        (folder / "FULL-BUNDLE.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        instructions = (
            (
                "全套离线版：打开 GAMForge.app，选择自己的 GAM 即可转换。\n"
                "无需安装 Python、SDK 或编译器；也可运行 ./GAMForge-CLI。\n"
                "依赖内置于应用，请不要删除或修改应用内部内容；不含游戏。\n"
                "仅 ad-hoc 签名，未经过 Apple 公证；请先核对来源和 SHA-256。\n"
                "系统阻止打开时按隐私与安全性提示允许此应用，勿全局关闭安全保护。\n"
                "EXE 放 A:\\系统\\程序；外置模式 RES 放 A:\\系统\\数据。\n"
            )
            if macos
            else (
                "全套离线版：完整解压后运行 GAMForge.exe，选择自己的 GAM 即可转换。\n无需安装 Python、SDK、编译器或手工填写依赖路径。\n请保留 dependencies 和 _internal 目录，不能只复制单个 EXE。\nEXE 放 A:\\系统\\程序；外置模式 RES 放 A:\\系统\\数据。\n需要 Windows 10/11 x64；不含游戏，不保证任意 GAM 兼容。\n"
            )
        )
        (folder / "开始使用.txt").write_text(instructions, encoding="utf-8")
        manifest = {
            p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*"))
            if p.is_file() and p.name != "MANIFEST.sha256.json"
        }
        (folder / "MANIFEST.sha256.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        staged = work / "full.zip"
        if macos:
            light_metadata["edition"] = "full"
            metadata_file.write_text(json.dumps(light_metadata, indent=2) + "\n", encoding="utf-8")
            audit_payload(folder, full=True)
            write_manifest(folder)
            archive_tree(folder, staged)
        else:
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
