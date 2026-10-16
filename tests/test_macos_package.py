"""Packaging logic tests are portable; these do not pretend to run a Mac app."""

import ast
import hashlib
import importlib.util
import json
import os
import plistlib
import stat
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("build_macos", SCRIPTS / "build_macos.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "build_macos", module)
    spec.loader.exec_module(module)
    return module


def symlink_or_skip(target, link, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"Host does not allow symlinks: {error}")


def test_mac_layout_keeps_dependencies_inside_app(mac, tmp_path):
    app, executable, deps = mac.mac_layout(tmp_path)
    assert app == tmp_path / "GAMForge.app"
    assert executable == app / "Contents/MacOS/GAMForge"
    assert deps == app / "Contents/Resources/dependencies"


def test_spec_explicitly_preserves_foreground_gui_and_console_workers():
    tree = ast.parse((SCRIPTS.parent / "packaging/macos.spec").read_text(encoding="utf-8"))
    calls = {
        node.func.id: node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    info = next(item.value for item in calls["BUNDLE"].keywords if item.arg == "info_plist")
    fields = {key.value: value for key, value in zip(info.keys, info.values)}
    assert isinstance(fields["LSBackgroundOnly"], ast.Constant)
    assert fields["LSBackgroundOnly"].value is False
    console = next(item.value for item in calls["EXE"].keywords if item.arg == "console")
    assert console.value is True


@pytest.mark.parametrize("background", [None, True, False])
def test_actual_bundle_plist_must_explicitly_allow_foreground(mac, tmp_path, background):
    app = tmp_path / "GAMForge.app"
    (app / "Contents").mkdir(parents=True)
    value = {} if background is None else {"LSBackgroundOnly": background}
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(value))
    if background is False:
        mac.verify_foreground_app(app)
    else:
        with pytest.raises(ValueError, match="foreground"):
            mac.verify_foreground_app(app)


def test_host_check_refuses_cross_compile(mac, monkeypatch):
    monkeypatch.setattr(mac.sys, "platform", "linux")
    with pytest.raises(ValueError, match="macOS"):
        mac.require_native_host("arm64")


def test_lipo_input_precedes_variadic_architecture_option(mac, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(mac.subprocess, "run", lambda command, **kw: calls.append((command, kw)))
    executable = tmp_path / "native-boot"
    mac.verify_native(executable, "arm64")
    assert calls == [(["lipo", str(executable), "-verify_arch", "arm64"], {"check": True})]


def test_host_check_requires_matching_python_architecture(mac, monkeypatch):
    monkeypatch.setattr(mac.sys, "platform", "darwin")
    monkeypatch.setattr(mac.platform, "machine", lambda: "arm64")
    mac.require_native_host("arm64")
    with pytest.raises(ValueError, match="matching"):
        mac.require_native_host("x86_64")


@pytest.mark.parametrize("name", ["sample.gam", "sample.res", "clang.exe", "runtime.dll", "8.BIN"])
def test_light_mac_audit_rejects_private_and_windows_payload(mac, tmp_path, name):
    (tmp_path / name).write_bytes(b"sample")
    with pytest.raises(ValueError, match="artifact"):
        mac.audit_payload(tmp_path)


def test_full_mac_allows_authorized_firmware_but_not_games(mac, tmp_path):
    (tmp_path / "8.BIN").write_bytes(b"rom")
    mac.audit_payload(tmp_path, full=True)
    (tmp_path / "game.gam").write_bytes(b"game")
    with pytest.raises(ValueError):
        mac.audit_payload(tmp_path, full=True)


def test_zip_preserves_symlinks_and_file_permissions(mac, tmp_path):
    folder = tmp_path / "GAMForge"
    folder.mkdir()
    executable = folder / "native"
    executable.write_bytes(b"native")
    executable.chmod(0o755)
    symlink_or_skip("native", folder / "alias")
    mac.write_manifest(folder)
    archive = tmp_path / "package.zip"
    mac.archive_tree(folder, archive)
    with zipfile.ZipFile(archive) as zipped:
        link = zipped.getinfo("GAMForge/alias")
        assert link.create_system == 3
        assert stat.S_ISLNK(link.external_attr >> 16)
        assert zipped.read(link) == b"native"
        if os.name != "nt":
            assert zipped.getinfo("GAMForge/native").external_attr >> 16 & 0o111
        manifest = json.loads(zipped.read("GAMForge/MANIFEST.sha256.json"))
        assert manifest["alias"] == hashlib.sha256(b"native").hexdigest()
        metadata = json.loads(zipped.read("GAMForge/BUNDLE-FILES.json"))
        assert metadata["alias"] == {"type": "symlink", "target": "native"}
    assert (
        archive.with_suffix(".zip.sha256")
        .read_text()
        .startswith(hashlib.sha256(archive.read_bytes()).hexdigest())
    )


def test_directory_symlink_is_not_recursively_duplicated(mac, tmp_path):
    folder = tmp_path / "GAMForge"
    (folder / "Frameworks").mkdir(parents=True)
    (folder / "Frameworks/real").write_bytes(b"payload")
    symlink_or_skip("Frameworks", folder / "Resources", directory=True)
    archive = tmp_path / "app.zip"
    mac.archive_tree(folder, archive)
    with zipfile.ZipFile(archive) as zipped:
        assert "GAMForge/Resources" in zipped.namelist()
        assert "GAMForge/Resources/real" not in zipped.namelist()


def test_external_link_is_rejected(mac, tmp_path):
    folder = tmp_path / "GAMForge"
    folder.mkdir()
    (tmp_path / "private").write_bytes(b"private")
    symlink_or_skip("../private", folder / "alias")
    with pytest.raises(ValueError, match="external"):
        list(mac.entries(folder))


def test_dangling_link_is_rejected(mac, tmp_path):
    symlink_or_skip("missing", tmp_path / "alias")
    with pytest.raises(ValueError, match="Dangling"):
        list(mac.entries(tmp_path))


def test_isolated_mac_environment_drops_developer_overrides(mac, monkeypatch, tmp_path):
    monkeypatch.setenv("A9288_ROM8", "/private/8.BIN")
    monkeypatch.setenv("A9288T_SDK", "/private/sdk")
    monkeypatch.setenv("CPATH", "/private/headers")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/private/lib")
    monkeypatch.setenv("PYTHONPATH", "/private/python")
    env = mac.isolated_mac_environment(tmp_path)
    assert env["A9288_USER_DATA"] == str(tmp_path / "profile")
    assert env["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert not {"A9288_ROM8", "A9288T_SDK", "CPATH", "DYLD_LIBRARY_PATH", "PYTHONPATH"} & env.keys()


def test_minimum_os_is_verified_against_macho_load_commands(mac, monkeypatch, tmp_path):
    (tmp_path / "native").write_bytes(b"\xcf\xfa\xed\xfe" + b"fixture")
    monkeypatch.setattr(
        mac.subprocess,
        "check_output",
        lambda *a, **k: "cmd LC_BUILD_VERSION\ncmdsize 32\nplatform 1\nminos 11.0\n",
    )
    mac.verify_minimum_os(tmp_path, "11.0")
    with pytest.raises(ValueError, match="newer than"):
        mac.verify_minimum_os(tmp_path, "10.15")
    monkeypatch.setattr(
        mac.subprocess,
        "check_output",
        lambda *a, **k: "cmd LC_VERSION_MIN_MACOSX\ncmdsize 16\nversion 12.0\nsdk 15.0\n",
    )
    with pytest.raises(ValueError, match="newer than"):
        mac.verify_minimum_os(tmp_path, "11.0")


def test_toolchain_rejects_homebrew_or_rpath_libraries(mac, monkeypatch, tmp_path):
    monkeypatch.setattr(
        mac.subprocess,
        "check_output",
        lambda *a, **k: "clang:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1)\n",
    )
    mac.verify_system_libraries(tmp_path / "clang")
    monkeypatch.setattr(
        mac.subprocess,
        "check_output",
        lambda *a, **k: "clang:\n\t@rpath/libLLVM.dylib (compatibility version 1)\n",
    )
    with pytest.raises(ValueError, match="Non-portable"):
        mac.verify_system_libraries(tmp_path / "clang")


def test_full_bundle_mac_smoke_with_mocked_native_tools(mac, monkeypatch, tmp_path):
    """Exercise archive/data integration, not Mach-O execution, on all hosts."""
    spec = importlib.util.spec_from_file_location("full_bundle", SCRIPTS / "build_full_bundle.py")
    full = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(full)
    source = tmp_path / "light"
    _, executable, _ = mac.mac_layout(source)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"MOCK MACH-O")
    (source / "MACOS-BUNDLE.json").write_text(
        json.dumps(
            {
                "architecture": "arm64",
                "version": full.__version__,
                "minimum_os": "macOS 11.0",
            }
        )
    )
    sdk = tmp_path / "sdk/Down_Include"
    sdk.mkdir(parents=True)
    (sdk / "Dsys.h").write_text("/* header */")
    tools = tmp_path / "tools/bin"
    tools.mkdir(parents=True)
    for name in full.TOOLS:
        (tools / name).write_bytes(b"MOCK MACH-O")
    rom = tmp_path / "firmware.bin"
    rom.write_bytes(bytes(2 * 1024 * 1024))
    output = tmp_path / "full.zip"
    args = [
        "full",
        "--platform",
        "macos",
        "--architecture",
        "arm64",
        "--portable-dir",
        str(source),
        "--sdk",
        str(sdk.parent),
        "--toolchain",
        str(tools.parent),
        "--rom8",
        str(rom),
        "--rome",
        str(rom),
        "--output",
        str(output),
        "--authorized-redistribution",
    ]
    monkeypatch.setattr(sys, "argv", args)
    for name in ("require_native_host", "verify_native", "verify_system_libraries", "sign_app"):
        monkeypatch.setattr(mac, name, lambda *a: None)
    monkeypatch.setattr(full, "verify_9288_abi", lambda *a: None)
    monkeypatch.setattr(full.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(full.subprocess, "check_output", lambda *a, **k: "mock clang\n")

    def selftest(folder, work):
        deps = mac.mac_layout(folder)[2]
        return {
            "self_test": "PASS",
            "version": full.__version__,
            "dependencies": {
                "sdk": str(deps / "sdk9288"),
                "toolchain": str(deps / "toolchain"),
                "rom8": str(deps / "roms/8.BIN"),
                "rome": str(deps / "roms/E.BIN"),
            },
        }

    monkeypatch.setattr(mac, "frozen_self_test", selftest)
    full.main()
    with zipfile.ZipFile(output) as zipped:
        metadata = json.loads(zipped.read("GAMForge/FULL-BUNDLE.json"))
        assert metadata["platform"] == "macos"
        assert metadata["architecture"] == "arm64"
        assert metadata["notarized"] is False
        assert metadata["sdk_firmware_redistribution_authorized"] is True
        names = zipped.namelist()
        assert "GAMForge/GAMForge.app/Contents/Resources/dependencies/roms/8.BIN" in names
        assert not any(name.endswith((".exe", ".dll", ".gam")) for name in names)
        manifest = json.loads(zipped.read("GAMForge/MANIFEST.sha256.json"))
        for name, digest in manifest.items():
            assert hashlib.sha256(zipped.read("GAMForge/" + name)).hexdigest() == digest


def test_full_bundle_keeps_windows_isolation_contract(mac, monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("full_bundle", SCRIPTS / "build_full_bundle.py")
    full = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(full)
    monkeypatch.setenv("SYSTEMROOT", "C:/Windows")
    monkeypatch.setenv("A9288_ROM8", "private")
    env = full.isolated_environment(tmp_path)
    assert env["LOCALAPPDATA"] == str(tmp_path / "profile")
    assert env["PATH"] == str(Path("C:/Windows") / "System32")
    assert "A9288_ROM8" not in env


def test_full_bundle_rejects_external_resources_before_dependency_writes(
    mac, monkeypatch, tmp_path
):
    spec = importlib.util.spec_from_file_location("full_bundle", SCRIPTS / "build_full_bundle.py")
    full = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(full)
    source = tmp_path / "light"
    contents = source / "GAMForge.app/Contents"
    contents.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "preserve.txt").write_text("unchanged")
    symlink_or_skip(outside, contents / "Resources", directory=True)
    sdk = tmp_path / "sdk/Down_Include"
    sdk.mkdir(parents=True)
    (sdk / "Dsys.h").write_text("/* header */")
    rom = tmp_path / "firmware.bin"
    rom.write_bytes(bytes(2 * 1024 * 1024))
    monkeypatch.setattr(mac, "require_native_host", lambda *args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "full",
            "--platform",
            "macos",
            "--architecture",
            "arm64",
            "--portable-dir",
            str(source),
            "--sdk",
            str(sdk.parent),
            "--toolchain",
            str(tmp_path / "tools"),
            "--rom8",
            str(rom),
            "--rome",
            str(rom),
            "--output",
            str(tmp_path / "full.zip"),
            "--authorized-redistribution",
        ],
    )
    with pytest.raises(ValueError, match="external package symlink"):
        full.main()
    assert list(outside.iterdir()) == [outside / "preserve.txt"]
    assert (outside / "preserve.txt").read_text() == "unchanged"
    assert not (tmp_path / "full.zip").exists()


@pytest.fixture
def tk_notices(tmp_path):
    versions = {"tcl": "8.6.16", "tk": "8.6.17"}
    payload = {"schema": 1}
    for component, version in versions.items():
        data = f"Test {component} {version} license notice.\n".encode()
        filename = f"{component}-license.terms"
        (tmp_path / filename).write_bytes(data)
        payload[component] = {
            "version": version,
            "source_url": f"https://raw.githubusercontent.com/tcltk/{component}/"
            f"core-{version.replace('.', '-')}/license.terms",
            "path": filename,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    path = tmp_path / "TCLTK-NOTICES.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload, versions


def test_tk_notices_preserve_exact_version_hash_and_provenance(mac, tk_notices, tmp_path):
    manifest, payload, versions = tk_notices
    destination = tmp_path / "notices"
    provenance = mac.collect_tk_notices(manifest, destination, versions)
    for name in ("tcl", "tk"):
        assert provenance[name] == {
            key: payload[name][key] for key in ("version", "source_url", "sha256")
        }
        assert (
            hashlib.sha256((destination / f"{name}-license.terms").read_bytes()).hexdigest()
            == (provenance[name]["sha256"])
        )
        assert "path" not in provenance[name]


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("version", "8.6.15", "runtime version"),
        ("sha256", "0" * 64, "SHA-256"),
        ("source_url", "https://example.com/license.terms", "official versioned source"),
        (
            "source_url",
            "https://raw.githubusercontent.com/tcltk/tk/main/license.terms",
            "official versioned source",
        ),
        ("path", "../outside-license.terms", "escapes"),
        ("path", "not-present.terms", "missing"),
    ],
)
def test_tk_notices_fail_closed_without_emitting_partial_bundle(
    mac, tk_notices, tmp_path, field, value, error
):
    manifest, payload, versions = tk_notices
    payload["tk"][field] = value
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    destination = tmp_path / "notices"
    with pytest.raises(ValueError, match=error):
        mac.collect_tk_notices(manifest, destination, versions)
    assert not destination.exists()


def test_tk_notices_require_manifest_and_supported_schema(mac, tk_notices, tmp_path):
    manifest, payload, versions = tk_notices
    with pytest.raises(ValueError, match="manifest missing"):
        mac.collect_tk_notices(tmp_path / "absent.json", tmp_path / "notices", versions)
    payload["schema"] = 2
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        mac.collect_tk_notices(manifest, tmp_path / "notices", versions)


def test_tk_notices_reject_unknown_runtime_version(mac, tk_notices, tmp_path):
    manifest, _, versions = tk_notices
    versions["tk"] = "8.6"
    with pytest.raises(ValueError, match="runtime version"):
        mac.collect_tk_notices(manifest, tmp_path / "notices", versions)


def test_tk_notices_reject_oversized_or_non_utf8_files(mac, tk_notices, tmp_path):
    manifest, payload, versions = tk_notices
    notice = tmp_path / payload["tk"]["path"]
    notice.write_bytes(b"x" * (128 * 1024 + 1))
    with pytest.raises(ValueError, match="128 KiB"):
        mac.collect_tk_notices(manifest, tmp_path / "notices", versions)
    notice.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        mac.collect_tk_notices(manifest, tmp_path / "notices", versions)


def test_tk_runtime_uses_patchlevel_and_destroys_probe(mac, monkeypatch):
    class Root:
        tk = None
        destroyed = False

        def __init__(self):
            self.tk = self

        def withdraw(self):
            pass

        def eval(self, command):
            return {"info patchlevel": "8.6.16", "package present Tk": "8.6.17"}[command]

        def destroy(self):
            self.destroyed = True

    root = Root()
    monkeypatch.setitem(sys.modules, "tkinter", SimpleNamespace(Tk=lambda: root))
    assert mac.tcl_tk_runtime_versions() == {"tcl": "8.6.16", "tk": "8.6.17"}
    assert root.destroyed


def test_license_collection_records_tk_provenance_in_metadata(
    mac, monkeypatch, tk_notices, tmp_path
):
    manifest, _, versions = tk_notices
    prefix = tmp_path / "python"
    prefix.mkdir()
    (prefix / "LICENSE.txt").write_text("Test Python notice")
    dependency_notice = tmp_path / "LICENSE.dependency"
    dependency_notice.write_text("Test dependency notice")

    class Distribution:
        files = [Path("LICENSE")]
        version = "test-build"

        def locate_file(self, name):
            return dependency_notice

    monkeypatch.setattr(mac.sys, "base_prefix", str(prefix))
    monkeypatch.setattr(mac.sysconfig, "get_path", lambda name: str(prefix))
    monkeypatch.setattr(mac.importlib.metadata, "distribution", lambda name: Distribution())
    monkeypatch.setattr(mac, "tcl_tk_runtime_versions", lambda: versions)
    folder = tmp_path / "bundle"
    folder.mkdir()
    notices = mac.collect_licenses(folder, manifest)
    metadata = json.loads((folder / "licenses/build-components.json").read_text())
    assert metadata["TclTk"] == notices
    assert metadata["TclTk"]["tcl"]["version"] == "8.6.16"
    assert metadata["TclTk"]["tk"]["version"] == "8.6.17"
