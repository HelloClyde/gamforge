"""Publication must never silently fall back to light or untested packages."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_full_release", ROOT / "scripts/check_full_release.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
SHA = "a" * 40


@pytest.fixture
def release(tmp_path):
    for host in CHECK.HOSTS:
        archive = tmp_path / f"gamforge-1.5.0-full-{host}.zip"
        metadata = {
            "edition": "full",
            "version": "1.5.0",
            "targets": sorted(CHECK.TARGETS),
            "games_included": False,
            "sdk_firmware_redistribution_authorized": True,
        }
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("GAMForge/FULL-BUNDLE.json", json.dumps(metadata))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_suffix(".zip.sha256").write_text(
            f"{digest}  {archive.name}\n", encoding="ascii"
        )
        evidence = {
            "result": "PASS",
            "bundle_host": host,
            "version": "1.5.0",
            "source_sha": SHA,
            "archive_sha256": digest,
            "cases": [
                {"target": t, "external_resources": e, "relocated_bundle": e, "result": "PASS"}
                for t, e in [(t, False) for t in sorted(CHECK.TARGETS)] + [("9288t", True)]
            ],
        }
        (tmp_path / f"validation-{host}.json").write_text(json.dumps(evidence), encoding="utf-8")
    return tmp_path


def test_all_full_packages_required(release):
    assert len(CHECK.check_assets(release, "v1.5.0", SHA)) == 9
    (release / "validation-macos-arm64.json").unlink()
    with pytest.raises(ValueError, match="asset set"):
        CHECK.check_assets(release, "v1.5.0", SHA)


def test_light_package_never_published(release):
    (release / "gamforge-1.5.0-windows-x64.zip").write_bytes(b"light")
    with pytest.raises(ValueError, match="Full-only"):
        CHECK.check_assets(release, "v1.5.0", SHA)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("result", "FAIL", "failed"),
        ("bundle_host", "windows-x64", "host"),
        ("version", "1.4.0", "version"),
        ("source_sha", "b" * 40, "source"),
        ("archive_sha256", "0" * 64, "archive"),
        ("cases", [], "tests"),
    ],
)
def test_evidence_is_bound_to_archive_source_and_host(release, field, value, error):
    path = release / "validation-macos-arm64.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=error):
        CHECK.check_assets(release, "v1.5.0", SHA)


@pytest.mark.parametrize("change", ["duplicate_target", "failed_case", "not_relocated"])
def test_four_targets_and_relocation_must_all_pass(release, change):
    path = release / "validation-windows-x64.json"
    data = json.loads(path.read_text())
    if change == "duplicate_target":
        data["cases"][0] = data["cases"][1]
    elif change == "failed_case":
        data["cases"][0]["result"] = "FAIL"
    else:
        data["cases"][-1]["relocated_bundle"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="coverage|relocated"):
        CHECK.check_assets(release, "v1.5.0", SHA)


def test_checksum_cannot_name_other_archive(release):
    archive = release / "gamforge-1.5.0-full-windows-x64.zip"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  other.zip\n")
    with pytest.raises(ValueError, match="Checksum"):
        CHECK.check_assets(release, "v1.5.0", SHA)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("edition", "light", "Not a Full"),
        ("version", "1.4.0", "version"),
        ("targets", ["9288"], "SDK"),
        ("games_included", True, "games"),
        ("sdk_firmware_redistribution_authorized", False, "authorization"),
    ],
)
def test_archive_manifest_must_be_full_even_with_valid_evidence(release, field, value, error):
    archive = release / "gamforge-1.5.0-full-windows-x64.zip"
    with zipfile.ZipFile(archive) as zipped:
        metadata = json.loads(zipped.read("GAMForge/FULL-BUNDLE.json"))
    metadata[field] = value
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("GAMForge/FULL-BUNDLE.json", json.dumps(metadata))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    path = release / "validation-windows-x64.json"
    evidence = json.loads(path.read_text())
    evidence["archive_sha256"] = digest
    path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match=error):
        CHECK.check_assets(release, "v1.5.0", SHA)


def test_workflow_requires_successful_full_jobs_and_publishes_no_light_glob():
    workflow = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
    full_job = workflow.split("\n  full:\n", 1)[1].split("\n  release:\n", 1)[0]
    release_job = workflow.split("\n  release:\n", 1)[1]
    assert "needs: [windows, macos, toolchain]" in full_job
    assert "--authorized-redistribution" in full_job
    assert "build_release_full.py" in full_job
    assert "needs: full" in release_job
    assert "pattern: gamforge-full-*" in release_job
    assert "check_full_release.py" in release_job
    assert "dist/*-full-*.zip" in release_job
    assert "dist/*.zip" not in release_job
    assert "continue-on-error" not in full_job + release_job
