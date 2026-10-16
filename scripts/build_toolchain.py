"""Build and validate pinned S1C33 tools natively on Windows or macOS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("clang", "ld.lld", "llvm-objcopy", "llvm-readelf")
MACOS_DEPLOYMENT_TARGET = "11.0"


def run(*command):
    subprocess.run(list(map(str, command)), check=True)


def capture(*command):
    return subprocess.check_output(list(map(str, command)), text=True, errors="replace")


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def host_tag(system: str | None = None, machine: str | None = None) -> str:
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    if system == "Windows" and arch == "x86_64":
        return "windows-x64"
    if system == "Darwin" and arch in {"arm64", "x86_64"}:
        return "macos-" + arch
    raise ValueError(f"Unsupported build host: {system}/{machine}; use Windows x64 or native macOS")


def deployment_target(value: str) -> str:
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value) or tuple(map(int, value.split("."))) < (
        11,
        0,
    ):
        raise argparse.ArgumentTypeError("macOS deployment target must be 11.0 or newer")
    return value


def cmake_options(tag: str, minimum_macos: str) -> list[str]:
    options = [
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DLLVM_ENABLE_PROJECTS=clang;lld",
        "-DLLVM_TARGETS_TO_BUILD=",
        "-DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD=S1C33",
        "-DLLVM_INCLUDE_TESTS=OFF",
        "-DLLVM_INCLUDE_BENCHMARKS=OFF",
        "-DLLVM_INCLUDE_EXAMPLES=OFF",
        "-DLLVM_ENABLE_ASSERTIONS=OFF",
        "-DLLVM_ENABLE_ZLIB=OFF",
        "-DLLVM_ENABLE_ZSTD=OFF",
        "-DLLVM_ENABLE_LIBXML2=OFF",
        "-DLLVM_ENABLE_LIBEDIT=OFF",
        "-DLLVM_ENABLE_CURL=OFF",
        "-DLLVM_ENABLE_TERMINFO=OFF",
        "-DLLVM_BUILD_LLVM_DYLIB=OFF",
        "-DLLVM_LINK_LLVM_DYLIB=OFF",
        "-DCLANG_LINK_CLANG_DYLIB=OFF",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DCLANG_ENABLE_STATIC_ANALYZER=OFF",
        "-DCLANG_ENABLE_ARCMT=OFF",
        "-DLLVM_PARALLEL_LINK_JOBS=1",
    ]
    if tag.startswith("macos-"):
        # The HOST tools use Apple libc++; their OUTPUT is still S1C33 ELF.
        options += [
            "-DCMAKE_C_COMPILER=/usr/bin/clang",
            "-DCMAKE_CXX_COMPILER=/usr/bin/clang++",
            "-DLLVM_ENABLE_LIBCXX=ON",
            f"-DCMAKE_OSX_ARCHITECTURES={tag.removeprefix('macos-')}",
            f"-DCMAKE_OSX_DEPLOYMENT_TARGET={minimum_macos}",
        ]
    return options


def install_tools(build_bin: Path, output: Path, tag: str) -> None:
    suffix = ".exe" if tag.startswith("windows-") else ""
    (output / "bin").mkdir(parents=True, exist_ok=True)
    # The multicall programs inspect argv[0]. Copy bytes to their PUBLIC name;
    # wrappers executing lld/readobj would change linker/output dialect.
    candidates = {
        "clang": ("clang",),
        "ld.lld": ("ld.lld", "lld"),
        "llvm-objcopy": ("llvm-objcopy",),
        "llvm-readelf": ("llvm-readelf", "llvm-readobj"),
    }
    for tool, names in candidates.items():
        origin = next(
            (
                build_bin / (name + suffix)
                for name in names
                if (build_bin / (name + suffix)).is_file()
            ),
            None,
        )
        if origin is None:
            raise FileNotFoundError(f"Missing built tool: {tool} in {build_bin}")
        destination = output / "bin" / (tool + suffix)
        shutil.copy2(origin, destination, follow_symlinks=True)
        if not suffix:
            destination.chmod(destination.stat().st_mode | 0o111)


def verify_macos_binary(tool: Path, tag: str) -> None:
    expected = tag.removeprefix("macos-")
    architectures = capture("/usr/bin/lipo", "-archs", tool).split()
    if architectures != [expected]:
        raise ValueError(f"{tool.name}: expected native {expected}, got {architectures}")
    # Reject build-tree/Homebrew rpaths so runner-installed libraries cannot
    # hide absent dependencies on the user's Mac.
    dependencies = capture("/usr/bin/otool", "-L", tool).splitlines()[1:]
    for line in dependencies:
        dependency = line.strip().split(" (", 1)[0]
        if not dependency.startswith(("/usr/lib/", "/System/Library/")):
            raise ValueError(f"Non-system runtime dependency in {tool.name}: {dependency}")


def verify_toolchain(output: Path, tag: str) -> None:
    """Exercise the installed tools, not build-tree executables or --version alone."""
    suffix = ".exe" if tag.startswith("windows-") else ""
    tools = {name: output / "bin" / (name + suffix) for name in TOOLS}
    for tool in tools.values():
        if not tool.is_file():
            raise FileNotFoundError(tool)
        if tag.startswith("macos-"):
            if not os.access(tool, os.X_OK):
                raise ValueError(f"Tool is not executable: {tool}")
            verify_macos_binary(tool, tag)
        run(tool, "--version")
    sys.path.insert(0, str(ROOT / "src"))
    from a9288.compiler.build import verify_9288_abi

    verify_9288_abi(str(tools["clang"]))
    with tempfile.TemporaryDirectory(prefix="gamforge-toolchain-probe-") as temporary:
        work = Path(temporary)
        (work / "entry.c").write_text(
            "extern unsigned helper(unsigned); unsigned entry(void) { return helper(5); }\n"
        )
        (work / "helper.c").write_text("unsigned helper(unsigned x) { return x + 7; }\n")
        for stem in ("entry", "helper"):
            run(
                tools["clang"],
                "--target=s1c33-none-elf",
                "-Os",
                "-ffreestanding",
                "-c",
                work / (stem + ".c"),
                "-o",
                work / (stem + ".o"),
            )
        run(
            tools["ld.lld"],
            "--entry=entry",
            "-Ttext=0x2700000",
            "-o",
            work / "probe.elf",
            work / "entry.o",
            work / "helper.o",
        )
        if (work / "probe.elf").read_bytes()[:6] != b"\x7fELF\x01\x01":
            raise ValueError("Expected a 32-bit little-endian S1C33 ELF")
        symbols = capture(tools["llvm-readelf"], "-h", "-s", work / "probe.elf")
        if "Symbol table" not in symbols or not all(
            name in symbols for name in ("entry", "helper")
        ):
            raise ValueError("llvm-readelf must run in GNU readelf mode and list linked symbols")
        run(tools["llvm-objcopy"], "-O", "binary", work / "probe.elf", work / "probe.bin")
        if not 0 < (work / "probe.bin").stat().st_size < 65536:
            raise ValueError("Invalid linked probe binary")
    print(f"Native {tag}: GNU33 ABI + compile/link/readelf/objcopy PASS")


def write_archive(output: Path) -> Path:
    archive = output.with_suffix(".zip")
    # Preserve +x for macOS Archive Utility/unzip; aliases are regular files.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(output.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo.from_file(path, path.relative_to(output.parent).as_posix())
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | stat.S_IMODE(path.stat().st_mode)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as stream, zipped.open(info, "w", force_zip64=True) as member:
                shutil.copyfileobj(stream, member)
    archive.with_suffix(".zip.sha256").write_text(
        f"{file_sha256(archive)}  {archive.name}\n", encoding="utf-8"
    )
    return archive


def reusable_output(output: Path, expected: dict) -> bool:
    try:
        actual = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if any(actual.get(key) != value for key, value in expected.items()):
            return False
        files = actual["files"]
        suffix = ".exe" if expected["host"].startswith("windows-") else ""
        required = {f"bin/{tool}{suffix}" for tool in TOOLS}
        required |= {"LLVM-LICENSE.TXT", expected["patch"]}
        if set(files) != required:
            return False
        installed = {
            path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()
        }
        if installed != required | {"manifest.json"}:
            return False
        return all(file_sha256(output / name) == digest for name, digest in files.items())
    except (OSError, KeyError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build/toolchain")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--deployment-target", type=deployment_target, default=MACOS_DEPLOYMENT_TARGET
    )
    parser.add_argument("--expect-host", help="Fail if this is not the expected native runner")
    parser.add_argument(
        "--reuse", action="store_true", help="Reuse a hash-verified existing package"
    )
    parser.add_argument(
        "--verify-only", type=Path, help="Test an installed toolchain without building"
    )
    args = parser.parse_args()
    tag = host_tag()
    if args.expect_host and args.expect_host != tag:
        parser.error(f"Expected {args.expect_host}, running on {tag}")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.verify_only:
        verify_toolchain(args.verify_only.resolve(), tag)
        return
    manifest = json.loads((ROOT / "toolchain/manifest.json").read_text(encoding="utf-8"))
    patch = ROOT / "toolchain" / manifest["patch"]
    expected = {
        **manifest,
        "patch_sha256": file_sha256(patch),
        "host": tag,
        "deployment_target": args.deployment_target if tag.startswith("macos-") else None,
        "builder_sha256": file_sha256(Path(__file__)),
    }
    output = args.output_dir.resolve() / ("s1c33-9288-toolchain-" + tag)
    suffix = ".exe" if tag.startswith("windows-") else ""
    allowed = {f"bin/{tool}{suffix}" for tool in TOOLS}
    allowed |= {"manifest.json", "LLVM-LICENSE.TXT", patch.name}
    existing = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    if existing - allowed:
        raise SystemExit(
            f"Unexpected files in output; use a clean --output-dir: {sorted(existing - allowed)}"
        )
    if args.reuse and reusable_output(output, expected):
        verify_toolchain(output, tag)
        print(write_archive(output))
        return
    work = args.work_dir.resolve()
    source = work / "source"
    build = work / ("build-" + tag)
    if not source.exists():
        source.mkdir(parents=True)
        run("git", "init", source)
        run("git", "-C", source, "remote", "add", "origin", manifest["repository"])
        run("git", "-C", source, "fetch", "--depth=1", "origin", manifest["revision"])
        run("git", "-C", source, "checkout", "--detach", "FETCH_HEAD")
    if capture("git", "-C", source, "rev-parse", "HEAD").strip() != manifest["revision"]:
        raise SystemExit("Refusing to use a non-pinned source tree")
    check = subprocess.run(
        ["git", "-C", str(source), "apply", "--check", str(patch)], capture_output=True
    )
    if check.returncode == 0:
        run("git", "-C", source, "apply", patch)
    else:
        run("git", "-C", source, "apply", "--reverse", "--check", patch)
    run("cmake", "-S", source / "llvm", "-B", build, *cmake_options(tag, args.deployment_target))
    run(
        "cmake",
        "--build",
        build,
        "--parallel",
        args.jobs,
        "--target",
        "clang",
        "lld",
        "llvm-objcopy",
        "llvm-readobj",
    )
    install_tools(build / "bin", output, tag)
    verify_toolchain(output, tag)
    shutil.copy2(source / "llvm/LICENSE.TXT", output / "LLVM-LICENSE.TXT")
    shutil.copy2(patch, output / patch.name)
    expected["files"] = {
        path.relative_to(output).as_posix(): file_sha256(path)
        for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    (output / "manifest.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    archive = write_archive(output)
    print(archive)
    if tag == "windows-x64":
        legacy = args.output_dir.resolve() / "s1c33-9288-toolchain.zip"
        shutil.copy2(archive, legacy)
        legacy.with_suffix(".zip.sha256").write_text(
            f"{file_sha256(legacy)}  {legacy.name}\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
