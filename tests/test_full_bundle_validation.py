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
