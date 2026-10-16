"""Host/tool packaging contracts; Mac native execution is a separate CI gate."""

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
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
    make_package(tmp_path, expected)
    assert builder.reusable_output(tmp_path, expected)
    assert not builder.reusable_output(tmp_path, {**expected, "host": "macos-x86_64"})
    assert not builder.reusable_output(tmp_path, {**expected, "builder_sha256": "different"})
    (tmp_path / "bin/ld.lld").write_bytes(b"changed")
    assert not builder.reusable_output(tmp_path, expected)


def make_package(root, expected, *, headers=True):
    files = {}
    names = [*("bin/" + tool for tool in builder.TOOLS), "LLVM-LICENSE.TXT", expected["patch"]]
    if headers:
        names += ["lib/clang/22/include/" + name for name in builder.REQUIRED_HEADERS]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        files[name] = builder.file_sha256(path)
    manifest = {**expected, "files": files}
    if headers:
        manifest["resource_headers"] = {
            "directory": "lib/clang/22/include",
            "origin": "build",
            "revision": expected["revision"],
        }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


@pytest.mark.parametrize("change", ["missing", "changed", "unlisted", "escape"])
def test_reuse_requires_authenticated_resource_headers(tmp_path, change):
    expected = {"host": "macos-arm64", "patch": "abi.patch", "revision": "pinned"}
    manifest = make_package(tmp_path, expected, headers=change != "missing")
    if change == "changed":
        (tmp_path / "lib/clang/22/include/stdarg.h").write_bytes(b"modified")
    elif change == "unlisted":
        (tmp_path / "lib/clang/22/include/rogue.h").write_bytes(b"extra")
    elif change == "escape":
        manifest["files"]["lib/clang/22/include/../../outside.h"] = "0" * 64
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert not builder.reusable_output(tmp_path, expected)


def test_install_resource_headers_keeps_nested_files_and_requires_standard_headers(tmp_path):
    source = tmp_path / "build/lib/clang/22/include"
    source.mkdir(parents=True)
    for name in (*builder.REQUIRED_HEADERS, "__stdarg_va_list.h"):
        (source / name).write_bytes(name.encode())
    (source / "nested").mkdir()
    (source / "nested/alias.h").write_bytes(b"nested")
    output = tmp_path / "output"
    include = output / "lib/clang/22/include"
    metadata = builder.install_resource_headers(source, output, include)
    assert metadata == {"directory": "lib/clang/22/include", "origin": "build"}
    assert (include / "nested/alias.h").read_bytes() == b"nested"
    with pytest.raises(ValueError, match="must be new"):
        builder.install_resource_headers(source, output, include)
    (source / "stdarg.h").unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        builder.install_resource_headers(source, output, output / "lib/clang/23/include")


def fake_pinned_headers(tmp_path, monkeypatch):
    checkout = tmp_path / "upstream"
    source = checkout / "clang/lib/Headers"
    source.mkdir(parents=True)
    tree = []
    for name in (*builder.REQUIRED_HEADERS, "__stdarg_va_list.h", "CMakeLists.txt"):
        data = ("upstream " + name).encode()
        (source / name).write_bytes(data)
        sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        tree.append(f"100644 blob {sha}\tclang/lib/Headers/{name}".encode())
    monkeypatch.setattr(
        builder, "capture", lambda *args: str(checkout) if args[-1] == "--show-toplevel" else "pin"
    )
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *args: b"\0".join(tree) + b"\0")
    return source


@pytest.mark.parametrize("change", [None, "edited", "extra", "revision", "wrong-directory"])
def test_sparse_source_import_authenticates_exact_git_blobs(tmp_path, monkeypatch, change):
    source = fake_pinned_headers(tmp_path, monkeypatch)
    manifest = {"revision": "pin"}
    if change == "edited":
        (source / "stdarg.h").write_bytes(b"modified")
    elif change == "extra":
        (source / "injected.h").write_bytes(b"extra")
    elif change == "revision":
        manifest["revision"] = "other"
    elif change == "wrong-directory":
        source = source.parent
    if change:
        with pytest.raises(ValueError):
            builder.pinned_source_headers(source, manifest)
    else:
        selected = builder.pinned_source_headers(source, manifest)
        assert set(selected) == {*builder.REQUIRED_HEADERS, "__stdarg_va_list.h"}


def test_resource_header_authentication_with_real_local_git(tmp_path):
    source = tmp_path / "clang/lib/Headers"
    source.mkdir(parents=True)
    for name in (*builder.REQUIRED_HEADERS, "CMakeLists.txt"):
        (source / name).write_bytes((name + "\n").encode())
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "core.autocrlf=false", "add", "."], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    revision = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()
    assert set(builder.pinned_source_headers(source, {"revision": revision})) == set(
        builder.REQUIRED_HEADERS
    )
    (source / "stdarg.h").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Git blob"):
        builder.pinned_source_headers(source, {"revision": revision})


@pytest.mark.parametrize("change", [None, "builder", "hash", "host", "extra", "output"])
def test_legacy_import_accepts_only_known_verified_package(tmp_path, monkeypatch, change):
    expected = {
        "host": "macos-arm64",
        "patch": "abi.patch",
        "revision": "pin",
        "deployment_target": "11.0",
        "builder_sha256": "current builder",
    }
    old = tmp_path / "old"
    legacy = {**expected, "builder_sha256": builder.LEGACY_BUILDER_SHA256}
    if change == "builder":
        legacy["builder_sha256"] = "unknown builder"
    elif change == "host":
        legacy["host"] = "macos-x86_64"
    make_package(old, legacy, headers=False)
    if change == "hash":
        (old / "bin/clang").write_bytes(b"modified")
    elif change == "extra":
        (old / "rogue").write_bytes(b"extra")
    output = tmp_path / "fixed"
    if change == "output":
        output.mkdir()
    source = fake_pinned_headers(tmp_path, monkeypatch)
    probes = []
    monkeypatch.setattr(builder, "verify_toolchain", lambda *args, **kwargs: probes.append(kwargs))
    monkeypatch.setattr(
        builder, "resource_include", lambda clang, root: root / "lib/clang/22/include"
    )
    if change:
        with pytest.raises(ValueError):
            builder.import_legacy_tools(old, source, output, expected)
        assert not probes
    else:
        provenance = builder.import_legacy_tools(old, source, output, expected)
        assert probes == [{"require_headers": False}]
        assert provenance["imported_tools"]["builder_sha256"] == builder.LEGACY_BUILDER_SHA256
        assert provenance["resource_headers"]["origin"] == "pinned-source"
        assert (output / "lib/clang/22/include/stdarg.h").read_bytes() == b"upstream stdarg.h"
        builder.finish_package(output, {**expected, **provenance})
        assert builder.reusable_output(output, expected)


def test_header_probe_is_required_by_default_and_avoids_host_sdk():
    source = (ROOT / "scripts/build_toolchain.py").read_text()
    assert "require_headers: bool = True" in source
    assert "clang-resource-headers" in source
    for name in builder.REQUIRED_HEADERS:
        assert "#include <" + name + ">" in source
    assert 'header_flags = ["-nostdinc", "-isystem", str(include)]' in source


def test_ci_requires_two_real_mac_architectures_and_extracted_verification():
    workflow = (ROOT / ".github/workflows/toolchain.yml").read_text()
    assert "macos-15-intel" in workflow
    assert "macos-arm64" in workflow
    assert "macos-x86_64" in workflow
    assert "--verify-only" in workflow
    assert "shasum -a 256 -c" in workflow
    assert "workflow_call:" in workflow
