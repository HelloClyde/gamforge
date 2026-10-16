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
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("clang", "ld.lld", "llvm-objcopy", "llvm-readelf")
MACOS_DEPLOYMENT_TARGET = "11.0"
# The first native CI build omitted Clang's resource headers. This exact builder
# is the ONLY legacy package accepted by --import-tools; it is not a general
# bypass of builder provenance checks.
LEGACY_BUILDER_SHA256 = "81eb9911dc10195cd0bf4e38c9640075bd4fbbf2e2a851f43a39891ad00136c9"
REQUIRED_HEADERS = ("stdarg.h", "stddef.h", "stdint.h")


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


def resource_include(clang: Path, root: Path) -> Path:
    resource = Path(capture(clang, "-print-resource-dir").strip()).resolve()
    relative = resource.relative_to(root.resolve()).as_posix()
    if not re.fullmatch(r"lib/clang/\d+", relative):
        raise ValueError(f"Unexpected Clang resource directory: {resource}")
    return resource / "include"


def regular_files(root: Path) -> set[str]:
    """Do not follow a package link into another directory while hashing/copying."""
    if root.is_symlink():
        raise ValueError(f"Symlink package root rejected: {root}")
    files = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Symlink package member rejected: {path}")
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def install_resource_headers(source: Path, output: Path, include: Path) -> dict:
    relative = include.relative_to(output.resolve()).as_posix()
    if not re.fullmatch(r"lib/clang/\d+/include", relative):
        raise ValueError(f"Invalid resource header destination: {include}")
    files = regular_files(source)
    if not set(REQUIRED_HEADERS).issubset(files):
        raise ValueError("Incomplete Clang resource headers")
    if include.exists():
        raise ValueError("Resource header destination must be new")
    shutil.copytree(source, include)
    return {"directory": relative, "origin": "build"}


def pinned_source_headers(source: Path, manifest: dict) -> dict[str, Path]:
    """Allow sparse source checkouts, but authenticate every copied Git blob."""
    if source.is_symlink():
        raise ValueError("Symlink resource header directory rejected")
    source = source.resolve()
    checkout = Path(capture("git", "-C", source, "rev-parse", "--show-toplevel").strip())
    if source != (checkout / "clang/lib/Headers").resolve():
        raise ValueError("Expected the checkout's clang/lib/Headers directory")
    if capture("git", "-C", checkout, "rev-parse", "HEAD").strip() != manifest["revision"]:
        raise ValueError("Resource headers are not from the pinned revision")
    source_files = regular_files(source)
    tree = subprocess.check_output(
        [
            "git",
            "-C",
            str(checkout),
            "ls-tree",
            "-rz",
            manifest["revision"],
            "--",
            "clang/lib/Headers",
        ]
    )
    tracked = {}
    selected = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        attributes, filename = entry.split(b"\t", 1)
        mode, kind, blob = attributes.decode("ascii").split()
        relative = PurePosixPath(filename.decode("utf-8")).relative_to("clang/lib/Headers")
        if kind != "blob" or mode not in ("100644", "100755") or ".." in relative.parts:
            raise ValueError(f"Non-regular source header member: {relative}")
        path = source.joinpath(*relative.parts)
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if actual != blob:
            raise ValueError(f"Resource header differs from pinned Git blob: {relative}")
        tracked[relative.as_posix()] = path
        if relative.suffix in (".h", ".inc", ".modulemap"):
            selected[relative.as_posix()] = path
    if source_files != set(tracked):
        raise ValueError("Untracked/missing files in resource header source")
    if not set(REQUIRED_HEADERS).issubset(selected):
        raise ValueError("Pinned source is missing required resource headers")
    return selected


def verify_toolchain(output: Path, tag: str, *, require_headers: bool = True) -> None:
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
    header_flags = []
    header_probe = ""
    if require_headers:
        include = resource_include(tools["clang"], output)
        if not set(REQUIRED_HEADERS).issubset(regular_files(include)):
            raise ValueError("Missing installed Clang resource headers")
        # Never let host SDK headers hide a missing distributable resource tree.
        header_flags = ["-nostdinc", "-isystem", str(include)]
        header_probe = (
            "#include <stdarg.h>\n#include <stddef.h>\n#include <stdint.h>\n"
            '_Static_assert(sizeof(uint32_t) == 4, "uint32_t");\n'
            '_Static_assert(sizeof(size_t) == 4, "size_t");\n'
            '_Static_assert(sizeof(va_list) > 0, "va_list");\n'
        )
    with tempfile.TemporaryDirectory(prefix="gamforge-toolchain-probe-") as temporary:
        work = Path(temporary)
        (work / "entry.c").write_text(
            header_probe
            + "extern unsigned helper(unsigned); unsigned entry(void) { return helper(5); }\n"
        )
        (work / "helper.c").write_text("unsigned helper(unsigned x) { return x + 7; }\n")
        for stem in ("entry", "helper"):
            run(
                tools["clang"],
                "--target=s1c33-none-elf",
                "-Os",
                "-ffreestanding",
                *header_flags,
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


def _package_matches(output: Path, expected: dict, *, require_headers: bool) -> bool:
    try:
        actual = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if any(actual.get(key) != value for key, value in expected.items()):
            return False
        files = actual["files"]
        suffix = ".exe" if expected["host"].startswith("windows-") else ""
        required = {f"bin/{tool}{suffix}" for tool in TOOLS}
        required |= {"LLVM-LICENSE.TXT", expected["patch"]}
        if require_headers:
            headers = actual["resource_headers"]
            prefix = headers["directory"]
            if (
                not re.fullmatch(r"lib/clang/\d+/include", prefix)
                or headers["origin"] not in ("build", "pinned-source")
                or headers["revision"] != expected["revision"]
            ):
                return False
            extra = set(files) - required
            if not {prefix + "/" + name for name in REQUIRED_HEADERS}.issubset(extra):
                return False
            for name in extra:
                path = PurePosixPath(name)
                if (
                    not name.startswith(prefix + "/")
                    or path.is_absolute()
                    or ".." in path.parts
                    or "\\" in name
                    or ":" in name
                    or path.as_posix() != name
                ):
                    return False
            required |= extra
        if set(files) != required or regular_files(output) != required | {"manifest.json"}:
            return False
        if (
            "patch_sha256" in expected
            and file_sha256(output / expected["patch"]) != expected["patch_sha256"]
        ):
            return False
        return all(file_sha256(output / name) == digest for name, digest in files.items())
    except (OSError, KeyError, TypeError, ValueError):
        return False


def reusable_output(output: Path, expected: dict) -> bool:
    return _package_matches(output, expected, require_headers=True)


def import_legacy_tools(old: Path, headers: Path, output: Path, expected: dict) -> dict:
    """Repair only the known, hash-verified first macOS CI artifacts in a NEW tree."""
    if not expected["host"].startswith("macos-") or expected["deployment_target"] != "11.0":
        raise ValueError("Legacy import supports only the first macOS 11.0 native builds")
    legacy = {**expected, "builder_sha256": LEGACY_BUILDER_SHA256}
    if not _package_matches(old, legacy, require_headers=False):
        raise ValueError("Legacy toolchain provenance, file set or hashes do not match")
    if output.exists():
        raise ValueError("Legacy import output must be new")
    selected = pinned_source_headers(headers, expected)
    verify_toolchain(old, expected["host"], require_headers=False)
    shutil.copytree(old, output)
    include = resource_include(output / "bin/clang", output)
    for name, source in selected.items():
        destination = include / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return {
        "resource_headers": {
            "directory": include.relative_to(output.resolve()).as_posix(),
            "origin": "pinned-source",
            "revision": expected["revision"],
        },
        "imported_tools": {
            "builder_sha256": LEGACY_BUILDER_SHA256,
            "manifest_sha256": file_sha256(old / "manifest.json"),
            "revision": expected["revision"],
        },
    }


def finish_package(output: Path, expected: dict) -> Path:
    expected = dict(expected)
    expected["files"] = {
        name: file_sha256(output / name)
        for name in sorted(regular_files(output))
        if name != "manifest.json"
    }
    (output / "manifest.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    return write_archive(output)


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
    parser.add_argument("--import-tools", type=Path, help="Repair the known first macOS CI package")
    parser.add_argument(
        "--resource-headers", type=Path, help="Pinned Git checkout's clang/lib/Headers for repair"
    )
    args = parser.parse_args()
    tag = host_tag()
    if args.expect_host and args.expect_host != tag:
        parser.error(f"Expected {args.expect_host}, running on {tag}")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if bool(args.import_tools) != bool(args.resource_headers):
        parser.error("--import-tools and --resource-headers must be supplied together")
    if args.verify_only and (args.import_tools or args.reuse):
        parser.error("--verify-only cannot be combined with import/reuse")
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
    if args.import_tools:
        provenance = import_legacy_tools(
            args.import_tools.resolve(), args.resource_headers.resolve(), output, expected
        )
        verify_toolchain(output, tag)
        print(finish_package(output, {**expected, **provenance}))
        return
    suffix = ".exe" if tag.startswith("windows-") else ""
    allowed = {f"bin/{tool}{suffix}" for tool in TOOLS}
    allowed |= {"manifest.json", "LLVM-LICENSE.TXT", patch.name}
    existing = regular_files(output)
    allowed |= {name for name in existing if re.fullmatch(r"lib/clang/\d+/include/.+", name)}
    if existing - allowed:
        raise SystemExit(
            f"Unexpected files in output; use a clean --output-dir: {sorted(existing - allowed)}"
        )
    if args.reuse and reusable_output(output, expected):
        verify_toolchain(output, tag)
        print(write_archive(output))
        return
    if any(name.startswith("lib/clang/") for name in existing):
        raise SystemExit("Use a clean --output-dir for a non-reusable resource header tree")
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
        "clang-resource-headers",
    )
    install_tools(build / "bin", output, tag)
    include = resource_include(output / "bin" / ("clang" + suffix), output)
    if include.exists():
        # Existing headers are only reused when the complete manifest passed above.
        # Do not delete a computed tree just to conceal an inconsistent old cache.
        raise SystemExit("Use a clean --output-dir for a non-reusable resource header tree")
    resource_headers = install_resource_headers(
        resource_include(build / "bin" / ("clang" + suffix), build), output, include
    )
    resource_headers["revision"] = manifest["revision"]
    verify_toolchain(output, tag)
    shutil.copy2(source / "llvm/LICENSE.TXT", output / "LLVM-LICENSE.TXT")
    shutil.copy2(patch, output / patch.name)
    archive = finish_package(output, {**expected, "resource_headers": resource_headers})
    print(archive)
    if tag == "windows-x64":
        legacy = args.output_dir.resolve() / "s1c33-9288-toolchain.zip"
        shutil.copy2(archive, legacy)
        legacy.with_suffix(".zip.sha256").write_text(
            f"{file_sha256(legacy)}  {legacy.name}\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
