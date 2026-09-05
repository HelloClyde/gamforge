"""Build a pinned upstream LLVM checkout plus the local 9288 ABI patch."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(list(map(str, command)), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "toolchain/manifest.json").read_text())
    work = ROOT / "build/toolchain"
    source = work / "source"
    build = work / "build"
    patch = ROOT / "toolchain" / manifest["patch"]
    if not source.exists():
        source.mkdir(parents=True)
        run("git", "init", source)
        run("git", "-C", source, "remote", "add", "origin", manifest["repository"])
        run("git", "-C", source, "fetch", "--depth=1", "origin", manifest["revision"])
        run("git", "-C", source, "checkout", "--detach", "FETCH_HEAD")
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != manifest["revision"]:
        raise SystemExit("Refusing to use a non-pinned source tree")
    check = subprocess.run(
        ["git", "-C", str(source), "apply", "--check", str(patch)], capture_output=True
    )
    if check.returncode == 0:
        run("git", "-C", source, "apply", patch)
    else:
        run("git", "-C", source, "apply", "--reverse", "--check", patch)
    run(
        "cmake",
        "-S",
        source / "llvm",
        "-B",
        build,
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
        "-DCLANG_ENABLE_STATIC_ANALYZER=OFF",
        "-DCLANG_ENABLE_ARCMT=OFF",
        "-DLLVM_PARALLEL_LINK_JOBS=1",
    )
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
    output = ROOT / "dist/s1c33-9288-toolchain"
    (output / "bin").mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if os.name == "nt" else ""
    for tool in manifest["tools"]:
        name = "llvm-readobj" if tool == "llvm-readelf" else tool
        shutil.copyfile(build / "bin" / (name + suffix), output / "bin" / (tool + suffix))
    from a9288.compiler.build import verify_9288_abi

    verify_9288_abi(str(output / "bin" / ("clang" + suffix)))
    shutil.copyfile(source / "llvm/LICENSE.TXT", output / "LLVM-LICENSE.TXT")
    shutil.copyfile(patch, output / patch.name)
    manifest["patch_sha256"] = hashlib.sha256(patch.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.make_archive(str(output), "zip", output.parent, output.name)
    print(output.with_suffix(".zip"))


if __name__ == "__main__":
    main()
