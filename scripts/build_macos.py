"""Build native macOS .app/CLI ZIPs on a matching Mac, without SDKs or games.

No cross-compiling, Wine, Developer ID or notarization is implied. PyInstaller
framework symlinks and executable permissions are preserved in the archive.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

from a9288 import __version__
from a9288.compiler.boot import build_helper, bundled_helper

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURES = ("arm64", "x86_64")
FORBIDDEN = {".gam", ".res", ".sav", ".rom", ".map", ".raw", ".flat", ".exe", ".dll"}


def mac_layout(folder):
    app = folder / "GAMForge.app"
    return app, app / "Contents/MacOS/GAMForge", app / "Contents/Resources/dependencies"


def verify_foreground_app(app):
    """Console-enabled BUNDLE defaults to background-only unless overridden."""
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("LSBackgroundOnly") is not False or info.get("LSUIElement", False):
        raise ValueError("GAMForge.app must be a foreground app with LSBackgroundOnly=false")


def require_native_host(architecture):
    if sys.platform != "darwin":
        raise ValueError("Build macOS distributions on macOS, not Windows/Linux or Wine")
    if architecture not in ARCHITECTURES or platform.machine() != architecture:
        raise ValueError("Use a matching native Mac/Python architecture for each distribution")


def entries(folder):
    """Do not follow directory links; refuse dangling or external links."""
    root = folder.resolve()
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            target = os.readlink(path)
            if Path(target).is_absolute() or not path.resolve().is_relative_to(root):
                raise ValueError(f"Unsafe external package symlink: {path}")
            if not path.exists():
                raise ValueError(f"Dangling package symlink: {path}")
        yield path


def audit_payload(folder, *, full=False):
    for path in entries(folder):
        if path.is_dir() and not path.is_symlink():
            continue
        # Only the explicitly authorized two firmware files belong in full builds.
        if path.suffix.lower() in FORBIDDEN or (
            not full and path.name.upper() in ("8.BIN", "E.BIN")
        ):
            raise ValueError(f"Private game, firmware or non-native artifact: {path}")


def write_manifest(folder):
    """Hash regular bytes and link text, recording link types/modes separately."""
    metadata = {}
    for path in entries(folder):
        if path.name in ("MANIFEST.sha256.json", "BUNDLE-FILES.json"):
            continue
        relative = path.relative_to(folder).as_posix()
        if path.is_symlink():
            metadata[relative] = {"type": "symlink", "target": os.readlink(path)}
        elif path.is_file():
            metadata[relative] = {"type": "file", "mode": stat.S_IMODE(path.stat().st_mode)}
    (folder / "BUNDLE-FILES.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {}
    for path in entries(folder):
        if path.name == "MANIFEST.sha256.json":
            continue
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8")
        elif path.is_file():
            data = path.read_bytes()
        else:
            continue
        manifest[path.relative_to(folder).as_posix()] = hashlib.sha256(data).hexdigest()
    (folder / "MANIFEST.sha256.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def archive_tree(folder, archive):
    """Unix ZIP attributes retain .app symlinks and executable permissions."""
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in entries(folder):
            name = (Path(folder.name) / path.relative_to(folder)).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zipped.writestr(info, os.readlink(path).encode("utf-8"))
            elif path.is_file():
                zipped.write(path, name)
            elif path.is_dir():
                zipped.write(path, name + "/")
    archive.with_suffix(".zip.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n",
        encoding="ascii",
    )


def sign_app(app):
    # Ad-hoc signing is required for native arm64 execution, but conveys no
    # publisher identity and is NOT Apple notarization. Re-sign after changes.
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def verify_native(executable, architecture):
    subprocess.run(["lipo", "-verify_arch", architecture, str(executable)], check=True)


def verify_system_libraries(executable):
    """Full tools must not silently depend on Homebrew or a developer build tree."""
    output = subprocess.check_output(["otool", "-L", str(executable)], text=True)
    for line in output.splitlines()[1:]:
        library = line.strip().split(" (", 1)[0]
        if not library.startswith(("/usr/lib/", "/System/Library/")):
            raise ValueError(f"Non-portable dependency {library} in {executable}")


def version_tuple(version):
    return tuple((list(map(int, version.split("."))) + [0, 0])[:3])


def verify_minimum_os(folder, minimum):
    """Reject an advertised minimum older than any bundled Mach-O slice."""
    mach_o_magics = {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
        b"\xca\xfe\xba\xbf",
        b"\xbf\xba\xfe\xca",
    }
    for path in entries(folder):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic not in mach_o_magics:
            continue
        output = subprocess.check_output(["otool", "-l", str(path)], text=True)
        # Both modern LC_BUILD_VERSION and older LC_VERSION_MIN_MACOSX exist.
        targets = re.findall(r"\bminos\s+(\d+(?:\.\d+)*)", output)
        targets += re.findall(
            r"LC_VERSION_MIN_MACOSX\s+cmdsize\s+\d+\s+version\s+"
            r"(\d+(?:\.\d+)*)",
            output,
        )
        if not targets:
            raise ValueError(f"Cannot verify macOS deployment target: {path}")
        if any(version_tuple(value) > version_tuple(minimum) for value in targets):
            raise ValueError(
                f"{path} requires macOS {max(targets, key=version_tuple)}, "
                f"newer than advertised {minimum}"
            )


def tcl_tk_runtime_versions():
    """Ask the Python/Tk runtime being frozen, not a neighboring installation."""
    import tkinter

    root = tkinter.Tk()
    try:
        root.withdraw()
        return {
            "tcl": root.tk.eval("info patchlevel"),
            "tk": root.tk.eval("package present Tk"),
        }
    finally:
        root.destroy()


def collect_tk_notices(manifest_path, destination, versions):
    """Consume explicit matching upstream notices; never scan other Pythons."""
    if not manifest_path.is_file():
        raise ValueError(f"Tcl/Tk notices manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Unsupported Tcl/Tk notices manifest schema")
    provenance = {}
    contents = {}
    for component in ("tcl", "tk"):
        entry = manifest.get(component)
        version = versions.get(component, "")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError(f"Unsupported {component} runtime version: {version}")
        if not isinstance(entry, dict) or entry.get("version") != version:
            raise ValueError(f"{component} notice must match runtime version {version}")
        expected_url = (
            f"https://raw.githubusercontent.com/tcltk/{component}/"
            f"core-{version.replace('.', '-')}/license.terms"
        )
        if entry.get("source_url") != expected_url:
            raise ValueError(f"{component} notice must reference its official versioned source")
        relative = Path(entry.get("path", ""))
        source = (manifest_path.parent / relative).resolve()
        if relative.is_absolute() or not source.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError(f"{component} notice path escapes its manifest directory")
        if not source.is_file():
            raise ValueError(f"{component} notice file missing: {relative}")
        if not 0 < source.stat().st_size <= 128 * 1024:
            raise ValueError(f"{component} notice must be a non-empty file up to 128 KiB")
        data = source.read_bytes()
        data.decode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        if entry.get("sha256") != digest:
            raise ValueError(f"{component} notice SHA-256 mismatch")
        provenance[component] = {
            "version": version,
            "source_url": expected_url,
            "sha256": digest,
        }
        contents[component] = data
    # Validate both notices before emitting anything; copy verified bytes.
    destination.mkdir(parents=True, exist_ok=True)
    for component, data in contents.items():
        (destination / f"{component}-license.terms").write_bytes(data)
    return provenance


def collect_licenses(folder, tk_manifest):
    target = folder / "licenses"
    target.mkdir(exist_ok=True)
    license_file = next(
        (
            prefix / name
            for prefix in (Path(sys.base_prefix), Path(sysconfig.get_path("stdlib")))
            for name in ("LICENSE.txt", "LICENSE_PYTHON.txt", "LICENSE")
            if (prefix / name).is_file()
        ),
        None,
    )
    if license_file is None:
        raise ValueError("CPython license missing from build environment")
    shutil.copyfile(license_file, target / "CPython-LICENSE.txt")
    components = {"CPython": sys.version.split()[0]}
    for package in ("Pillow", "PyInstaller"):
        installed = importlib.metadata.distribution(package)
        notices = [
            p for p in installed.files or [] if p.name.upper().startswith(("LICENSE", "COPYING"))
        ]
        if not notices:
            raise ValueError(f"Missing license metadata: {package}")
        destination = target / package
        destination.mkdir(exist_ok=True)
        for index, path in enumerate(notices):
            shutil.copyfile(installed.locate_file(path), destination / f"{index}-{path.name}")
        components[package] = installed.version
    notices = collect_tk_notices(tk_manifest, target / "TclTk", tcl_tk_runtime_versions())
    components["TclTk"] = notices
    (target / "build-components.json").write_text(
        json.dumps(components, indent=2) + "\n", encoding="utf-8"
    )
    return notices


def isolated_mac_environment(work):
    forbidden = {
        "CC",
        "CXX",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "INCLUDE",
        "LIB",
        "LIBPATH",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
    }
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(("A9288", "ATSW600", "PYTHON", "CONDA"))
        and k.upper() not in forbidden
    }
    env.update(
        A9288_USER_DATA=str(work / "profile"),
        A9288_WORKSPACE=str(work / "work"),
        PATH="/usr/bin:/bin:/usr/sbin:/sbin",
    )
    return env


def frozen_self_test(folder, work):
    app, executable, _ = mac_layout(folder)
    verify_foreground_app(app)
    env = isolated_mac_environment(work)
    output = subprocess.check_output([str(executable), "--self-test"], env=env, cwd=work, text=True)
    report = json.loads(output)
    if report.get("self_test") != "PASS" or not report.get("boot_helper"):
        raise ValueError(f"Frozen macOS resources failed self-test: {report}")
    if report.get("version") != __version__:
        raise ValueError("Frozen package version differs from source version")
    subprocess.run(
        [str(executable), "--worker", "compiler.backend", "--help"], env=env, cwd=work, check=True
    )
    helper = folder / "GAMForge.app/Contents/Frameworks/a9288/data/bin/native-boot"
    if not helper.is_file():
        helper = folder / "GAMForge.app/Contents/Resources/a9288/data/bin/native-boot"
    result = subprocess.run([str(helper)], env=env, cwd=work, capture_output=True, text=True)
    if result.returncode not in (1, 2) or "usage" not in (result.stdout + result.stderr).lower():
        raise ValueError(f"Native boot helper did not run its usage path: {result}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=ARCHITECTURES, default=platform.machine())
    parser.add_argument("--minimum-macos", default="11.0")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/pyinstaller-macos")
    parser.add_argument("--archive-name")
    parser.add_argument(
        "--tk-notices-manifest",
        type=Path,
        required=True,
        help="Version/hash/source manifest for the current runtime's official Tcl/Tk notices",
    )
    args = parser.parse_args()
    try:
        require_native_host(args.architecture)
    except ValueError as error:
        parser.error(str(error))
    name = args.archive_name or f"gamforge-{__version__}-macos-{args.architecture}.zip"
    if Path(name).name != name or not name.endswith(".zip"):
        parser.error("archive-name must be a ZIP filename without directories")
    if not all(part.isdecimal() for part in args.minimum_macos.split(".")):
        parser.error("minimum-macos must be a dotted version")
    dist = args.dist_dir.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    helper = bundled_helper()
    previous_target = os.environ.get("MACOSX_DEPLOYMENT_TARGET")
    os.environ["MACOSX_DEPLOYMENT_TARGET"] = args.minimum_macos
    try:
        build_helper(helper, cc="clang")
    finally:
        if previous_target is None:
            os.environ.pop("MACOSX_DEPLOYMENT_TARGET", None)
        else:
            os.environ["MACOSX_DEPLOYMENT_TARGET"] = previous_target
    verify_native(helper, args.architecture)
    env = dict(
        os.environ,
        GAMFORGE_MAC_ARCH=args.architecture,
        GAMFORGE_MAC_MINIMUM=args.minimum_macos,
        MACOSX_DEPLOYMENT_TARGET=args.minimum_macos,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(args.work_dir.resolve()),
            str(ROOT / "packaging/macos.spec"),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    # Assemble in a fresh temporary tree, so stale resources cannot enter releases.
    with tempfile.TemporaryDirectory(prefix="macos-package-", dir=dist) as temporary:
        folder = Path(temporary) / "GAMForge"
        folder.mkdir()
        shutil.copytree(dist / "GAMForge.app", folder / "GAMForge.app", symlinks=True)
        wrapper = folder / "GAMForge-CLI"
        wrapper.write_text(
            '#!/bin/sh\nset -eu\nbase=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'exec "$base/GAMForge.app/Contents/MacOS/GAMForge" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        for file in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
            shutil.copyfile(ROOT / file, folder / file)
        shutil.copytree(ROOT / "docs", folder / "docs")
        shutil.copytree(ROOT / "toolchain", folder / "toolchain")
        tk_notices = collect_licenses(folder, args.tk_notices_manifest.resolve())
        (folder / "MACOS-BUNDLE.json").write_text(
            json.dumps(
                {
                    "version": __version__,
                    "platform": "macos",
                    "architecture": args.architecture,
                    "minimum_os": "macOS " + args.minimum_macos,
                    "edition": "light",
                    "signing": "ad-hoc",
                    "notarized": False,
                    "games_included": False,
                    "tcl_tk_notices": tk_notices,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (folder / "开始使用.txt").write_text(
            "macOS 原生轻量版：打开 GAMForge.app；命令行可运行 ./GAMForge-CLI。\n"
            "不包含 SDK、S1C33 工具链、固件和游戏，转换前需配置匹配架构的依赖。\n"
            "程序仅 ad-hoc 签名，未经过 Apple 公证。请先核对来源和 SHA-256；\n"
            "系统阻止打开时，按 macOS 隐私与安全性中的提示允许此应用，勿全局关闭安全保护。\n",
            encoding="utf-8",
        )
        app, executable, _ = mac_layout(folder)
        audit_payload(folder)
        verify_native(executable, args.architecture)
        verify_minimum_os(folder, args.minimum_macos)
        sign_app(app)
        frozen_self_test(folder, Path(temporary))
        subprocess.run([str(wrapper), "--version"], check=True)
        write_manifest(folder)
        archive = dist / name
        archive_tree(folder, archive)
    print(f"Built {archive} ({archive.stat().st_size} bytes); ad-hoc signed, NOT notarized")


if __name__ == "__main__":
    main()
