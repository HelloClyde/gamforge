"""Expired cache recovery must not weaken toolchain provenance or execute inputs."""

import importlib
import json
from pathlib import Path

import pytest
from test_full_release import create_zip, toolchain_files

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def bootstrap(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module = importlib.import_module("restore_toolchain_cache")
    release = importlib.import_module("build_release_full")
    extract = module.extract_verified
    # Offline Windows/Linux tests use link-free synthetic Mac archives. The
    # real Mac jobs retain ditto extraction and native executable probes.
    monkeypatch.setattr(
        module,
        "extract_verified",
        lambda archive, output, root, **kwargs: extract(archive, output, root, windows=True),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Bootstrap must never execute imported programs")

    monkeypatch.setattr(release.subprocess, "run", forbidden)
    return module, release


def package(tmp_path, release, host, mutate=None):
    name = "s1c33-9288-toolchain-" + host
    payload = toolchain_files(release, host)
    if mutate:
        mutate(payload)
    archive = tmp_path / "inputs" / (name + ".zip")
    create_zip(archive, {name + "/" + key: value for key, value in payload.items()})
    return archive, payload


@pytest.mark.parametrize("host", ["windows-x64", "macos-arm64", "macos-x86_64"])
def test_matching_pinned_package_restores_without_executing(bootstrap, tmp_path, host):
    module, release = bootstrap
    archive, payload = package(tmp_path, release, host)
    assert module.restore(archive.parent, tmp_path / "dist", host, module.file_sha256(archive))
    restored = tmp_path / "dist" / archive.stem
    assert release.reusable_output(restored, release.expected_toolchain(host))
    for name, expected in payload.items():
        assert (restored / name).read_bytes() == expected


@pytest.mark.parametrize("field", ["revision", "host", "builder_sha256", "patch_sha256"])
def test_source_or_builder_change_leaves_clean_source_build(bootstrap, tmp_path, field):
    module, release = bootstrap

    def change(payload):
        metadata = json.loads(payload["manifest.json"])
        metadata[field] = "changed"
        payload["manifest.json"] = json.dumps(metadata).encode()

    archive, _ = package(tmp_path, release, "windows-x64", change)
    assert not module.restore(
        archive.parent, tmp_path / "dist", "windows-x64", module.file_sha256(archive)
    )
    assert not (tmp_path / "dist").exists()


def test_modified_payload_never_becomes_an_executable_cache(bootstrap, tmp_path):
    module, release = bootstrap
    archive, _ = package(
        tmp_path, release, "windows-x64", lambda payload: payload.update({"bin/clang.exe": b"bad"})
    )
    assert not module.restore(
        archive.parent, tmp_path / "dist", "windows-x64", module.file_sha256(archive)
    )
    assert not (tmp_path / "dist").exists()
    with pytest.raises(ValueError, match="Pinned bootstrap archive checksum"):
        module.restore(archive.parent, tmp_path / "dist", "windows-x64", "0" * 64)


def test_unavailable_artifact_and_existing_cache_are_not_modified(bootstrap, tmp_path):
    module, release = bootstrap
    assert not module.restore(tmp_path / "missing", tmp_path / "dist", "windows-x64", "0" * 64)
    archive, _ = package(tmp_path, release, "windows-x64")
    output = tmp_path / "dist" / archive.stem
    output.mkdir(parents=True)
    (output / "keep").write_text("existing cache")
    assert not module.restore(
        archive.parent, output.parent, "windows-x64", module.file_sha256(archive)
    )
    assert (output / "keep").read_text() == "existing cache"


def test_bootstrap_keeps_normal_native_and_full_validation_gates():
    workflow = (SCRIPTS.parent / ".github/workflows/toolchain.yml").read_text(encoding="utf-8")
    assert "run-id: 39085910929" in workflow and "github-token: ${{ github.token }}" in workflow
    assert workflow.index("restore_toolchain_cache.py") < workflow.index("--reuse")
    assert "--verify-only" in workflow and "continue-on-error: true" in workflow
    assert "actions: read" in workflow and "contents: write" not in workflow
