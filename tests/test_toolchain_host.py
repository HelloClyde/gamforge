"""Host/tool packaging contracts; Mac native execution is a separate CI gate."""

import argparse
import importlib.util
import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_toolchain", ROOT / "scripts/build_toolchain.py"
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Windows", "AMD64", "windows-x64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "aarch64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x86_64"),
    ],
)
def test_native_host_tags(system, machine, expected):
    assert builder.host_tag(system, machine) == expected


@pytest.mark.parametrize(
    "system,machine", [("Linux", "arm64"), ("Windows", "ARM64"), ("Darwin", "i386")]
)
def test_unsupported_host_does_not_mislabel_package(system, machine):
    with pytest.raises(ValueError, match="Unsupported build host"):
        builder.host_tag(system, machine)


def test_macos_configuration_is_native_and_self_contained():
    options = builder.cmake_options("macos-arm64", "11.0")
    assert "-DCMAKE_OSX_ARCHITECTURES=arm64" in options
    assert "-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0" in options
    assert "-DCMAKE_CXX_COMPILER=/usr/bin/clang++" in options
    assert "-DLLVM_ENABLE_LIBCXX=ON" in options
    assert "-DLLVM_LINK_LLVM_DYLIB=OFF" in options
    assert "-DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD=S1C33" in options
    assert not any("OSX" in opt for opt in builder.cmake_options("windows-x64", "11.0"))


@pytest.mark.parametrize("value", ["10.15", "arm64", "11;something", "11", "-1.0"])
def test_invalid_deployment_targets(value):
    with pytest.raises(argparse.ArgumentTypeError):
        builder.deployment_target(value)


@pytest.mark.parametrize("tag,suffix", [("windows-x64", ".exe"), ("macos-arm64", "")])
def test_multicall_aliases_are_copied_with_public_argv0(tmp_path, tag, suffix):
    build = tmp_path / "built"
    build.mkdir()
    for name in ("clang", "lld", "llvm-objcopy", "llvm-readobj"):
        path = build / (name + suffix)
        path.write_bytes(name.encode())
        path.chmod(0o755)
    output = tmp_path / "installed"
    builder.install_tools(build, output, tag)
    assert (output / "bin" / ("ld.lld" + suffix)).read_bytes() == b"lld"
    assert (output / "bin" / ("llvm-readelf" + suffix)).read_bytes() == b"llvm-readobj"
    assert not (output / "bin" / ("lld" + suffix)).exists()
    assert not (output / "bin" / ("llvm-readobj" + suffix)).exists()
    if os.name != "nt":
        assert (output / "bin" / ("clang" + suffix)).stat().st_mode & stat.S_IXUSR


def test_missing_built_tool_fails(tmp_path):
    with pytest.raises(FileNotFoundError, match="Missing built tool"):
        builder.install_tools(tmp_path / "empty", tmp_path / "output", "macos-arm64")


def test_archive_retains_file_modes_and_has_checksum(tmp_path):
    output = tmp_path / "s1c33-9288-toolchain-macos-arm64"
    (output / "bin").mkdir(parents=True)
    clang = output / "bin/clang"
    clang.write_bytes(b"native compiler")
    clang.chmod(0o755)
    archive = builder.write_archive(output)
    with zipfile.ZipFile(archive) as zipped:
        info = zipped.getinfo(output.name + "/bin/clang")
        assert info.create_system == 3
        assert stat.S_IMODE(info.external_attr >> 16) == stat.S_IMODE(clang.stat().st_mode)
        assert not stat.S_ISLNK(info.external_attr >> 16)
    assert archive.with_suffix(".zip.sha256").read_text().strip() == (
        builder.file_sha256(archive) + "  " + archive.name
    )


def test_native_mac_binary_must_match_arch_and_use_system_libraries(monkeypatch, tmp_path):
    tool = tmp_path / "clang"

    def capture(*args):
        if args[0].endswith("lipo"):
            return "arm64\n"
        return "clang:\n\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0)\n"

    monkeypatch.setattr(builder, "capture", capture)
    builder.verify_macos_binary(tool, "macos-arm64")
    with pytest.raises(ValueError, match="expected native x86_64"):
        builder.verify_macos_binary(tool, "macos-x86_64")


@pytest.mark.parametrize("library", ["/opt/homebrew/lib/libz.dylib", "@rpath/libLLVM.dylib"])
def test_mac_build_cannot_depend_on_runner_local_libraries(monkeypatch, tmp_path, library):
    monkeypatch.setattr(
        builder,
        "capture",
        lambda *args: "arm64\n"
        if args[0].endswith("lipo")
        else f"clang:\n\t{library} (compatibility version 1.0.0)\n",
    )
    with pytest.raises(ValueError, match="Non-system runtime dependency"):
        builder.verify_macos_binary(tmp_path / "clang", "macos-arm64")


def test_reuse_verifies_all_hashes_and_build_identity(tmp_path):
    expected = {
        "host": "macos-arm64",
        "patch": "abi.patch",
        "revision": "pinned",
        "builder_sha256": "script",
    }
    (tmp_path / "bin").mkdir()
    files = {}
    for name in [*("bin/" + tool for tool in builder.TOOLS), "LLVM-LICENSE.TXT", "abi.patch"]:
        path = tmp_path / name
        path.write_bytes(name.encode())
        files[name] = builder.file_sha256(path)
    (tmp_path / "manifest.json").write_text(json.dumps({**expected, "files": files}))
    assert builder.reusable_output(tmp_path, expected)
    assert not builder.reusable_output(tmp_path, {**expected, "host": "macos-x86_64"})
    assert not builder.reusable_output(tmp_path, {**expected, "builder_sha256": "different"})
    (tmp_path / "bin/ld.lld").write_bytes(b"changed")
    assert not builder.reusable_output(tmp_path, expected)


def test_ci_requires_two_real_mac_architectures_and_extracted_verification():
    workflow = (ROOT / ".github/workflows/toolchain.yml").read_text()
    assert "macos-15-intel" in workflow
    assert "macos-arm64" in workflow
    assert "macos-x86_64" in workflow
    assert "--verify-only" in workflow
    assert "shasum -a 256 -c" in workflow
    assert "workflow_call:" in workflow
