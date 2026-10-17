"""Offline contracts for full-package provenance and the original smoke fixture."""

import copy
import hashlib
import importlib.util
import io
import json
import stat
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from a9288.compiler import frontend

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def validator(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "verify_full_bundle", SCRIPTS / "verify_full_bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline tests must not access network or start subprocesses")

    monkeypatch.setattr(module, "urlopen", forbidden)
    monkeypatch.setattr(module.subprocess, "check_output", forbidden)
    monkeypatch.setattr(module.subprocess, "run", forbidden)
    monkeypatch.setenv("GITHUB_REPOSITORY", module.REPOSITORY)
    return module


@pytest.fixture(params=["arm64", "x86_64"])
def proof(validator, monkeypatch, tmp_path, request):
    architecture = request.param
    runner = validator.ARCHITECTURES[architecture]
    args = SimpleNamespace(
        app_run=1,
        toolchain_run=2,
        architecture=architecture,
        branch="codex/macos-support",
        sha="a" * 40,
        output=tmp_path / "provenance.json",
    )
    responses = {}
    bases = {}
    for kind, run_id, workflow, job_name, artifact, sha in (
        (
            "app",
            1,
            "build.yml",
            f"macOS portable application ({architecture})",
            f"macos-{architecture}",
            args.sha,
        ),
        (
            "toolchain",
            2,
            "toolchain.yml",
            f"toolchain ({runner}, macos-{architecture})",
            f"s1c33-9288-toolchain-macos-{architecture}",
            "b" * 40,
        ),
    ):
        base = f"repos/{validator.REPOSITORY}/actions/runs/{run_id}"
        bases[kind] = base
        responses[base] = {
            "repository": {"full_name": validator.REPOSITORY},
            "head_repository": {"full_name": validator.REPOSITORY},
            "path": ".github/workflows/" + workflow,
            "head_branch": args.branch,
            "head_sha": sha,
            "event": "workflow_dispatch",
            "status": "in_progress",
            "conclusion": None,
        }
        responses[base + "/jobs?per_page=100"] = {
            "total_count": 1,
            "jobs": [
                {
                    "id": run_id + 10,
                    "name": job_name,
                    "status": "completed",
                    "conclusion": "success",
                    "labels": [runner],
                }
            ],
        }
        responses[base + "/artifacts?per_page=100"] = {
            "total_count": 1,
            "artifacts": [
                {
                    "id": run_id + 20,
                    "name": artifact,
                    "expired": False,
                    "workflow_run": {"id": run_id, "head_sha": sha},
                }
            ],
        }
    monkeypatch.setattr(validator, "gh_json", lambda key: copy.deepcopy(responses[key]))
    return SimpleNamespace(args=args, responses=responses, bases=bases)


@pytest.mark.parametrize("conclusion", [None, "success", "failure"])
def test_successful_native_jobs_do_not_require_unrelated_jobs_to_finish(
    validator, proof, conclusion
):
    for base in proof.bases.values():
        proof.responses[base]["conclusion"] = conclusion
        proof.responses[base]["status"] = "in_progress" if conclusion is None else "completed"
    validator.check_runs(proof.args)
    result = json.loads(proof.args.output.read_text(encoding="utf-8"))
    assert result["source_sha"] == proof.args.sha
    assert result["app"]["head_sha"] == proof.args.sha
    # A different toolchain commit is allowed here; assemble separately checks builder hashes.
    assert result["toolchain"]["head_sha"] == "b" * 40
    for kind in ("app", "toolchain"):
        assert result[kind]["job_conclusion"] == "success"
        assert result[kind]["run_conclusion"] == conclusion


@pytest.mark.parametrize(
    "path,value,message",
    [
        (("repository", "full_name"), "someone/fork", "repository"),
        (("head_repository", "full_name"), "someone/fork", "Fork"),
        (("path",), ".github/workflows/other.yml", "workflow"),
        (("head_branch",), "main", "branch"),
        (("event",), "pull_request", "event"),
        (("conclusion",), "cancelled", "Cancelled"),
        (("head_sha",), "c" * 40, "exact source SHA"),
    ],
)
def test_app_run_provenance_must_match(validator, proof, path, value, message):
    record = proof.responses[proof.bases["app"]]
    for part in path[:-1]:
        record = record[part]
    record[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        validator.check_runs(proof.args)
    assert not proof.args.output.exists()


def test_validation_itself_must_run_in_the_official_repository(validator, proof, monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "someone/fork")
    with pytest.raises(ValueError, match="official repository"):
        validator.check_runs(proof.args)


@pytest.mark.parametrize("kind", ["app", "toolchain"])
@pytest.mark.parametrize(
    "field,value,message",
    [
        ("status", "in_progress", "portable application|toolchain"),
        ("conclusion", "failure", "portable application|toolchain"),
        ("name", "Different native job", "ambiguous native job"),
        ("labels", ["windows-2022"], "runner labels"),
    ],
)
def test_exact_native_job_must_have_succeeded(validator, proof, kind, field, value, message):
    jobs = proof.responses[proof.bases[kind] + "/jobs?per_page=100"]
    jobs["jobs"][0][field] = value
    with pytest.raises(ValueError, match=message):
        validator.check_runs(proof.args)


@pytest.mark.parametrize("kind", ["app", "toolchain"])
@pytest.mark.parametrize("collection", ["jobs", "artifacts"])
def test_pagination_or_ambiguous_matches_fail_closed(validator, proof, kind, collection):
    record = proof.responses[proof.bases[kind] + f"/{collection}?per_page=100"]
    record["total_count"] = 101
    with pytest.raises(ValueError, match="count"):
        validator.check_runs(proof.args)
    record["total_count"] = 2
    record[collection].append(copy.deepcopy(record[collection][0]))
    with pytest.raises(ValueError, match="ambiguous|Missing/expired"):
        validator.check_runs(proof.args)


@pytest.mark.parametrize("kind", ["app", "toolchain"])
@pytest.mark.parametrize(
    "path,value,message",
    [
        (("expired",), True, "expired"),
        (("name",), "other-artifact", "Missing"),
        (("workflow_run", "id"), 999, "another run"),
        (("workflow_run", "head_sha"), "c" * 40, "SHA mismatch"),
    ],
)
def test_artifact_is_bound_to_its_producing_run(validator, proof, kind, path, value, message):
    asset = proof.responses[proof.bases[kind] + "/artifacts?per_page=100"]["artifacts"][0]
    for part in path[:-1]:
        asset = asset[part]
    asset[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        validator.check_runs(proof.args)


def zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, target in entries:
            entry = zipfile.ZipInfo(name)
            if target is not None:
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, target if target is not None else b"fixture")
    return stream.getvalue()


def test_internal_links_are_allowed_without_materializing_them(validator):
    data = zip_bytes(
        [
            ("GAMForge/Contents/Resources/data", None),
            ("GAMForge/Contents/MacOS/data", "../Resources/data"),
        ]
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        validator.safe_members(archive, "GAMForge")


@pytest.mark.parametrize(
    "name,target",
    [
        ("../escape", None),
        ("/GAMForge/absolute", None),
        ("GAMForge/../../escape", None),
        ("OtherRoot/file", None),
        ("GAMForge/back\\slash", None),
        ("GAMForge/C:drive", None),
        ("GAMForge/Contents/link", "../../escape"),
        ("GAMForge/Contents/link", "/absolute"),
        ("GAMForge/Contents/link", "..\\escape"),
    ],
)
def test_zip_paths_and_links_cannot_escape(validator, name, target):
    with zipfile.ZipFile(io.BytesIO(zip_bytes([(name, target)]))) as archive:
        # Windows ZipInfo normalizes backslashes; also exercise the literal POSIX metadata.
        archive.infolist()[0].filename = name
        with pytest.raises(ValueError, match="Unsafe ZIP|Escaping ZIP"):
            validator.safe_members(archive, "GAMForge")


def test_duplicate_normalized_zip_member_is_rejected(validator):
    data = zip_bytes([("GAMForge/file", None), ("GAMForge/file/", None)])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with pytest.raises(ValueError, match="Duplicate ZIP"):
            validator.safe_members(archive, "GAMForge")


def test_verified_extraction_checks_hash_name_and_fresh_destination(
    validator, tmp_path, monkeypatch
):
    archive = tmp_path / "app.zip"
    archive.write_bytes(zip_bytes([("GAMForge/data", None)]))
    checksum = archive.with_suffix(".zip.sha256")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  app.zip\n", encoding="ascii")
    calls = []
    monkeypatch.setattr(validator.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    destination = tmp_path / "extracted"
    assert validator.extract_verified(archive, destination, "GAMForge") == destination / "GAMForge"
    assert calls == [(["ditto", "-x", "-k", str(archive), str(destination)], {"check": True})]
    calls.clear()
    checksum.write_text(f"{digest}  other.zip\n", encoding="ascii")
    with pytest.raises(ValueError, match="checksum name"):
        validator.extract_verified(archive, destination, "GAMForge")
    checksum.write_text(f"{'0' * 64}  app.zip\n", encoding="ascii")
    with pytest.raises(ValueError, match="checksum mismatch"):
        validator.extract_verified(archive, destination, "GAMForge")
    checksum.write_text(f"{digest}  app.zip\n", encoding="ascii")
    destination.mkdir()
    with pytest.raises(ValueError, match="destination must be new"):
        validator.extract_verified(archive, destination, "GAMForge")
    assert calls == []


def test_original_synthetic_game_is_deterministic_and_statically_resolvable(validator):
    game = validator.synthetic_game()
    assert isinstance(game, bytes)
    assert len(game) == 0x5000
    assert game[:4] == b"GAM\0"
    assert struct.unpack_from("<HI", game, 0x40) == (0x5046, 0x4000)
    assert hashlib.sha256(game).hexdigest() == validator.FIXTURE_SHA256
    assert validator.synthetic_game() == game
    report = frontend.analyze(game, frontend.DEFAULT_MAP)
    assert report["function_entries"] == 2
    assert report["recovered_guest_instructions"] == 8
    assert report["unresolved_direct_call_sites"] == 0
    assert report["unresolved_far_call_sites"] == 0
    assert report["indirect_jumps"] == 0


@pytest.mark.parametrize(
    "name",
    [
        "GAMForge/CON",
        "GAMForge/NUL.txt",
        "GAMForge/LPT9.log",
        "GAMForge/trailing.",
        "GAMForge/trailing ",
        "GAMForge/a?b",
        "GAMForge/./alias",
        "GAMForge//alias",
    ],
)
def test_windows_extraction_rejects_path_aliases_and_devices(validator, name):
    with zipfile.ZipFile(io.BytesIO(zip_bytes([(name, None)]))) as archive:
        with pytest.raises(ValueError, match="Unsafe"):
            validator.safe_members(archive, "GAMForge", windows=True)


def test_windows_rejects_even_internal_links_and_case_aliases(validator):
    data = zip_bytes([("GAMForge/link", "target")])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with pytest.raises(ValueError, match="links are not allowed"):
            validator.safe_members(archive, "GAMForge", windows=True)
    data = zip_bytes([("GAMForge/FILE", None), ("GAMForge/file", None)])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with pytest.raises(ValueError, match="Duplicate"):
            validator.safe_members(archive, "GAMForge", windows=True)


def test_windows_verified_extraction_needs_no_ditto(validator, tmp_path):
    archive = tmp_path / "app.zip"
    archive.write_bytes(zip_bytes([("GAMForge/sub/data", None)]))
    archive.with_suffix(".zip.sha256").write_text(
        f"{validator.digest(archive)}  {archive.name}\n", encoding="ascii"
    )
    root = validator.extract_verified(archive, tmp_path / "new", "GAMForge", windows=True)
    assert (root / "sub/data").read_bytes() == b"fixture"


def raw_snapshot_report(folder):
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / "c6502_boot_snapshot.bin"
    data = bytearray(64 + 32768)
    data[:8] = b"C65BOOT\0"
    struct.pack_into("<6I", data, 8, 2, 32768, 0x5046, 0, 0, 16)
    snapshot.write_bytes(data)
    object_path = snapshot.with_suffix(".o")
    object_path.write_bytes(b"synthetic ELF object")
    return {
        "boot_snapshot_object": str(object_path),
        "boot_snapshot_bytes": len(data),
        "boot_snapshot_compression": "none",
        "compressed_boot_snapshot_object": None,
        "compressed_boot_snapshot_bytes": 0,
    }


def test_current_raw_snapshot_report_with_retired_null_key(validator, tmp_path):
    report = raw_snapshot_report(tmp_path / "中文 快照")
    snapshot, data = validator.read_boot_snapshot(report)
    assert snapshot.name == "c6502_boot_snapshot.bin"
    assert len(data) == 32832


@pytest.mark.parametrize("object_name", [None, "", 42, []])
def test_missing_raw_snapshot_is_not_hidden_by_legacy_key(validator, tmp_path, object_name):
    report = raw_snapshot_report(tmp_path)
    report["compressed_boot_snapshot_object"] = report["boot_snapshot_object"]
    report["boot_snapshot_object"] = object_name
    with pytest.raises(ValueError, match="missing boot_snapshot_object"):
        validator.read_boot_snapshot(report)


@pytest.mark.parametrize("damage", ["object", "data", "size", "compression", "header", "pc"])
def test_raw_snapshot_contract_is_checked(validator, tmp_path, damage):
    report = raw_snapshot_report(tmp_path)
    object_path = Path(report["boot_snapshot_object"])
    snapshot = object_path.with_suffix(".bin")
    if damage == "object":
        object_path.unlink()
    elif damage == "data":
        snapshot.unlink()
    elif damage == "size":
        report["boot_snapshot_bytes"] += 1
    elif damage == "compression":
        report["boot_snapshot_compression"] = "lz4"
    else:
        data = bytearray(snapshot.read_bytes())
        if damage == "header":
            data[:8] = b"BROKEN!!"
        else:
            struct.pack_into("<I", data, 16, 0x6000)
        snapshot.write_bytes(data)
    with pytest.raises(ValueError):
        validator.read_boot_snapshot(report)


@pytest.mark.parametrize("macos", [False, True])
def test_verify_bundle_consumes_current_reports_for_all_five_modes(
    validator, tmp_path, monkeypatch, macos
):
    """Exercise the real report-consumption loop; only external CLI calls are faked."""
    monkeypatch.setattr(validator.sys, "platform", "darwin" if macos else "win32")
    monkeypatch.setattr(validator, "isolated_environment", lambda work: {})
    relative_cli = "GAMForge.app/Contents/MacOS/GAMForge" if macos else "GAMForge-CLI.exe"
    relative_deps = "GAMForge.app/Contents/Resources/dependencies" if macos else "dependencies"
    bundle = tmp_path / "Full 输入" / "GAMForge"
    cli = bundle / relative_cli
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"synthetic frozen CLI")
    (bundle / relative_deps).mkdir(parents=True)
    (bundle / "FULL-BUNDLE.json").write_text(
        json.dumps({"targets": ["9288", "9288t", "9288s", "tsw600"]}), encoding="utf-8"
    )
    monkeypatch.setattr(
        validator.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(
            {"self_test": "PASS", "boot_helper": True, "dependencies": {}}
        ),
    )
    conversions = []

    def run(command, **kwargs):
        if command[0] == "codesign":
            return
        assert command[1] == "convert"
        target = command[command.index("--target") + 1]
        external = "--external-resources" in command
        output = Path(command[command.index("--output") + 1])
        current_bundle = Path(command[0]).parents[3] if macos else Path(command[0]).parent
        output.write_bytes(b"D300" if target in ("9288s", "tsw600") else b"KF2\0")
        report = raw_snapshot_report(output.parent / "objects")
        report.update(
            target=target,
            external_resources=external,
            standalone_link_complete=True,
            runtime_interpreter_fallback=False,
            output_exe_sha256=validator.digest(output),
            sdk=str(current_bundle / relative_deps / "sdk"),
            display_scale="1.5x-sharp" if target == "9288t" else "2x" if target == "9288" else "1x",
        )
        if external:
            resource = output.parent / "synthetic.RES"
            resource.write_bytes(validator.synthetic_game())
            report.update(
                resource_file=resource.name,
                resource_sha256=validator.digest(resource),
                resource_install_directory="A:\\系统\\数据\\",
            )
        output.with_suffix(".report.json").write_text(json.dumps(report), encoding="utf-8")
        conversions.append((target, external))

    monkeypatch.setattr(validator.subprocess, "run", run)
    result = validator.verify_bundle(bundle, tmp_path / "isolated")
    assert conversions == [
        ("9288", False),
        ("9288t", False),
        ("9288s", False),
        ("tsw600", False),
        ("9288t", True),
    ]
    assert result["result"] == "PASS"
    assert all(case["boot_snapshot_bytes"] == 32832 for case in result["cases"])
    assert [case["relocated_bundle"] for case in result["cases"]] == [False] * 4 + [True]
