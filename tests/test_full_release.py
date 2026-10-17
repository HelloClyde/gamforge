"""Offline contracts for default same-run, native Full release packaging."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "build_release_full", SCRIPTS / "build_release_full.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Offline regression cannot start subprocesses or download dependencies"
        )

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    monkeypatch.setattr(module.subprocess, "check_output", forbidden)
    monkeypatch.setattr(module, "source_dependencies", forbidden)
    monkeypatch.setattr(module, "verify_bundle", forbidden)
    for name in tuple(module.os.environ):
        if name.startswith("GITHUB_"):
            monkeypatch.delenv(name)
    return module


def create_zip(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    path.with_suffix(".zip.sha256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n",
        encoding="ascii",
    )


def toolchain_files(builder, host):
    expected = builder.expected_toolchain(host)
    suffix = ".exe" if host == "windows-x64" else ""
    payload = {f"bin/{name}{suffix}": b"not-executable-fixture" for name in expected["tools"]}
    payload.update(
        {
            "LLVM-LICENSE.TXT": b"fixture license",
            expected["patch"]: (builder.ROOT / "toolchain" / expected["patch"]).read_bytes(),
            **{
                f"lib/clang/20/include/{name}": b"header"
                for name in ("stdarg.h", "stddef.h", "stdint.h")
            },
        }
    )
    manifest = {
        **expected,
        "resource_headers": {
            "directory": "lib/clang/20/include",
            "origin": "build",
            "revision": expected["revision"],
        },
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()},
    }
    payload["manifest.json"] = json.dumps(manifest).encode()
    return payload


@pytest.fixture(params=["windows-x64", "macos-arm64", "macos-x86_64"])
def assembly(builder, tmp_path, monkeypatch, request):
    host = request.param
    args = SimpleNamespace(
        host=host,
        app_artifacts=tmp_path / "app-artifacts",
        toolchain_artifacts=tmp_path / "tool-artifacts",
        work_dir=tmp_path / "work",
        output_dir=tmp_path / "release",
        vc_runtime=tmp_path / "VS/VC/Redist/MSVC/14.44.35208/x64/Microsoft.VC143.CRT"
        if host == "windows-x64"
        else None,
        authorized_redistribution=True,
    )
    if args.vc_runtime:
        args.vc_runtime.mkdir(parents=True)
        for name in builder.CRT_DLLS:
            (args.vc_runtime / name).write_bytes(b"redistributable-fixture")
    monkeypatch.setattr(builder, "host_tag", lambda: host)
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *args, **kwargs: "a" * 40 + "\n")
    version = builder.tomllib.loads((builder.ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]
    app_zip = args.app_artifacts / f"gamforge-{version}-{host}.zip"
    tools_name = f"s1c33-9288-toolchain-{host}"
    tools_zip = args.toolchain_artifacts / (tools_name + ".zip")
    create_zip(app_zip, {"GAMForge/README.md": b"light-fixture"})
    tool_payload = toolchain_files(builder, host)
    create_zip(tools_zip, {tools_name + "/" + name: data for name, data in tool_payload.items()})
    extract = builder.extract_verified
    extraction_calls = []

    def extract_native(archive, destination, root, *, windows):
        extraction_calls.append(windows)
        # Exercise real checks/extraction, using ZIPs with no Mac symlinks.
        return extract(archive, destination, root, windows=True)

    monkeypatch.setattr(builder, "extract_verified", extract_native)
    deps = tmp_path / "deps"
    for name in (
        "sdk9288/Down_Include/Dsys.h",
        "sdk9288t/include/Dsys.h",
        "sdk9288s/Down_Include/Dsys.h",
    ):
        path = deps / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"header")
    (deps / "roms").mkdir()
    for name in ("8.BIN", "E.BIN"):
        (deps / "roms" / name).write_bytes(b"\0" * (2 * 1024 * 1024))
    monkeypatch.setattr(builder, "source_dependencies", lambda work: deps)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs == {"check": True}
        if "--output" in command:
            archive = Path(command[command.index("--output") + 1])
            create_zip(archive, {"GAMForge/FULL-BUNDLE.json": b"{}"})

    monkeypatch.setattr(builder.subprocess, "run", run)
    conversions = []

    def verify(bundle, work):
        assert not args.output_dir.exists(), "Release output must wait for isolated conversion"
        conversions.append((bundle, work))
        return {
            "result": "PASS",
            "cases": [
                {
                    "target": target,
                    "external_resources": external,
                    "relocated_bundle": external,
                    "result": "PASS",
                }
                for target, external in (
                    ("9288", False),
                    ("9288t", False),
                    ("9288s", False),
                    ("tsw600", False),
                    ("9288t", True),
                )
            ],
        }

    monkeypatch.setattr(builder, "verify_bundle", verify)
    return SimpleNamespace(
        args=args,
        app_zip=app_zip,
        tools_zip=tools_zip,
        tools_name=tools_name,
        tool_payload=tool_payload,
        deps=deps,
        commands=commands,
        conversions=conversions,
        extraction_calls=extraction_calls,
        version=version,
    )


def test_native_full_assembly_verifies_then_emits_exact_assets(builder, assembly):
    evidence = builder.assemble(assembly.args)
    host = assembly.args.host
    archive_name = f"gamforge-{assembly.version}-full-{host}.zip"
    assert {path.name for path in assembly.args.output_dir.iterdir()} == {
        archive_name,
        archive_name + ".sha256",
        f"validation-{host}.json",
    }
    assert evidence["bundle_host"] == host
    assert evidence["version"] == assembly.version
    assert evidence["source_sha"] == "a" * 40
    assert evidence["public_dependencies_sha256"] == builder.PUBLIC_SHA256
    assert evidence["archive_sha256"] == builder.digest(assembly.args.output_dir / archive_name)
    assert evidence["toolchain_manifest"]["deployment_target"] == (
        None if host == "windows-x64" else "11.0"
    )
    assert evidence["release_published"] is False
    assert assembly.extraction_calls == [host == "windows-x64"] * 3
    assert len(assembly.conversions) == 1
    assert "--verify-only" in assembly.commands[0]
    assert assembly.commands[0][assembly.commands[0].index("--expect-host") + 1] == host
    assert "--authorized-redistribution" in assembly.commands[1]
    assert ("--vc-runtime" in assembly.commands[1]) == (host == "windows-x64")
    assert len(evidence["cases"]) == 5 and evidence["cases"][-1]["relocated_bundle"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "linux-x64"),
        ("builder_sha256", "0" * 64),
        ("patch_sha256", "0" * 64),
        ("revision", "0" * 40),
        ("deployment_target", "12.0"),
    ],
)
def test_toolchain_provenance_mismatch_never_executes_imported_tools(
    builder, assembly, field, value
):
    payload = assembly.tool_payload
    manifest = json.loads(payload["manifest.json"])
    manifest[field] = value
    payload["manifest.json"] = json.dumps(manifest).encode()
    create_zip(
        assembly.tools_zip,
        {assembly.tools_name + "/" + name: data for name, data in payload.items()},
    )
    with pytest.raises(ValueError, match="Toolchain manifest"):
        builder.assemble(assembly.args)
    assert assembly.commands == []
    assert not assembly.args.output_dir.exists()


def test_toolchain_payload_hash_mismatch_never_executes(builder, assembly):
    payload = assembly.tool_payload
    name = next(name for name in payload if name.startswith("bin/clang"))
    payload[name] = b"modified"
    create_zip(
        assembly.tools_zip,
        {assembly.tools_name + "/" + name: data for name, data in payload.items()},
    )
    with pytest.raises(ValueError, match="Toolchain manifest"):
        builder.assemble(assembly.args)
    assert assembly.commands == []


@pytest.mark.parametrize(
    "dependency", ["sdk9288t/include/Dsys.h", "sdk9288s/Down_Include/Dsys.h", "roms/E.BIN"]
)
def test_missing_target_dependencies_never_build_partial_full(builder, assembly, dependency):
    (assembly.deps / dependency).unlink()
    with pytest.raises(ValueError, match="Missing"):
        builder.assemble(assembly.args)
    assert len(assembly.commands) == 1
    assert not assembly.args.output_dir.exists()


@pytest.mark.parametrize("failure", ["raise", "not-pass", "missing-case"])
def test_failed_isolated_conversion_does_not_emit_release_assets(
    builder, assembly, monkeypatch, failure
):
    def fail(*args):
        if failure == "raise":
            raise RuntimeError("conversion failed")
        return {"result": "PASS" if failure == "missing-case" else "FAIL", "cases": []}

    monkeypatch.setattr(builder, "verify_bundle", fail)
    with pytest.raises((RuntimeError, ValueError)):
        builder.assemble(assembly.args)
    assert not assembly.args.output_dir.exists()


def test_explicit_authorization_required_before_any_work(builder, assembly):
    assembly.args.authorized_redistribution = False
    with pytest.raises(ValueError, match="authorization"):
        builder.assemble(assembly.args)
    assert not assembly.args.work_dir.exists()
    assert assembly.commands == []


def test_native_host_must_match(builder, assembly, monkeypatch):
    monkeypatch.setattr(builder, "host_tag", lambda: "unsupported-host")
    with pytest.raises(ValueError, match="matching native host"):
        builder.assemble(assembly.args)
    assert not assembly.args.work_dir.exists()


def test_existing_assets_not_overwritten(builder, assembly):
    assembly.args.output_dir.mkdir()
    existing = assembly.args.output_dir / f"validation-{assembly.args.host}.json"
    existing.write_text("previous")
    with pytest.raises(ValueError, match="overwrite"):
        builder.assemble(assembly.args)
    assert existing.read_text() == "previous"
    assert not assembly.args.work_dir.exists()


@pytest.mark.parametrize(
    "path",
    [
        None,
        "Windows/System32",
        "empty-redist",
        "VC/Redist/MSVC/14.44.35208/x86/Microsoft.VC143.CRT",
        "VC/Redist/MSVC/14.44.35208/debug_nonredist/x64/Microsoft.VC143.DebugCRT",
        "VC/Redist/MSVC/14.44.35208/x64/Microsoft.VC143.CRT",
    ],
)
def test_windows_requires_explicit_complete_redist(builder, tmp_path, monkeypatch, path):
    monkeypatch.setattr(builder, "host_tag", lambda: "windows-x64")
    runtime = tmp_path / path if path else None
    if runtime:
        runtime.mkdir(parents=True)
    args = SimpleNamespace(host="windows-x64", vc_runtime=runtime)
    with pytest.raises(ValueError, match="vc-runtime|exact VS|missing"):
        builder.validate_host(args)


def test_mac_refuses_windows_runtime(builder, tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "host_tag", lambda: "macos-arm64")
    with pytest.raises(ValueError, match="Windows VC runtime"):
        builder.validate_host(SimpleNamespace(host="macos-arm64", vc_runtime=tmp_path))


def test_ci_provenance_binds_same_run_to_actual_git_commit(builder, monkeypatch):
    sha = "a" * 40
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *args, **kwargs: sha + "\n")
    values = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_SHA": sha,
        "GITHUB_REPOSITORY": builder.REPOSITORY,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_WORKFLOW": "Build",
        "GITHUB_REF": "refs/tags/v1.5.1",
        "GITHUB_WORKFLOW_REF": f"{builder.REPOSITORY}/.github/workflows/build.yml@refs/tags/v1.5.1",
        "GITHUB_EVENT_NAME": "push",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    proof = builder.source_provenance()
    assert proof["source_sha"] == sha
    assert proof["github"]["run_id"] == "123"
    assert proof["github"]["run_attempt"] == "2"
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    with pytest.raises(ValueError, match="GITHUB_SHA"):
        builder.source_provenance()
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    with pytest.raises(ValueError, match="Untrusted"):
        builder.source_provenance()
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REPOSITORY", "some/fork")
    with pytest.raises(ValueError, match="official"):
        builder.source_provenance()
