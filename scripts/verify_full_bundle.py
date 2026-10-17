"""Assemble/test authorized Mac bundles; generated smoke input is never published.

Public dependencies are pinned by SHA256. Cross-run artifacts are accepted only
from the expected repository, workflow, branch, source and successful native job.
The verify command also runs against an existing Windows full bundle locally.
"""

import argparse
import hashlib
import json
import os
import platform
import posixpath
import shutil
import stat
import struct
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "HelloClyde/gamforge"
PUBLIC_ARCHIVE = "gamforge-1.4.0-full-windows-x64.zip"
PUBLIC_URL = f"https://github.com/{REPOSITORY}/releases/download/v1.4.0/{PUBLIC_ARCHIVE}"
PUBLIC_SHA256 = "42f60171e7fa4db8f9b1d17a64913ca40b77e0c60981437e445874fe0ae54fb4"
ARCHITECTURES = {"arm64": "macos-15", "x86_64": "macos-15-intel"}
FIXTURE_SHA256 = "acb021f6581e2f57dbc38b57755b0326348fde9dfacde10ebede015fc2884cbe"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def gh_json(endpoint):
    return json.loads(subprocess.check_output(["gh", "api", endpoint], text=True))


def check_runs(args):
    require(
        os.environ.get("GITHUB_REPOSITORY", REPOSITORY) == REPOSITORY,
        "Only artifacts from the official repository are accepted",
    )
    result = {"repository": REPOSITORY, "branch": args.branch, "source_sha": args.sha}
    runner = ARCHITECTURES[args.architecture]
    for kind, run_id, workflow, job_name, artifact in (
        (
            "app",
            args.app_run,
            ".github/workflows/build.yml",
            f"macOS portable application ({args.architecture})",
            f"macos-{args.architecture}",
        ),
        (
            "toolchain",
            args.toolchain_run,
            ".github/workflows/toolchain.yml",
            f"toolchain ({runner}, macos-{args.architecture})",
            f"s1c33-9288-toolchain-macos-{args.architecture}",
        ),
    ):
        endpoint = f"repos/{REPOSITORY}/actions/runs/{run_id}"
        run = gh_json(endpoint)
        require(run["repository"]["full_name"] == REPOSITORY, "Wrong artifact repository")
        require(run["head_repository"]["full_name"] == REPOSITORY, "Fork artifacts rejected")
        require(run["path"] == workflow, "Unexpected producing workflow")
        require(run["head_branch"] == args.branch, "Artifact branch differs from validation branch")
        require(run["event"] in ("push", "workflow_dispatch"), "Untrusted artifact event")
        require(run["conclusion"] != "cancelled", "Cancelled runs are not accepted")
        if kind == "app":
            require(run["head_sha"] == args.sha, "App must be built from this exact source SHA")
        jobs = gh_json(endpoint + "/jobs?per_page=100")
        require(jobs["total_count"] <= 100, "Unexpected job count; refusing partial validation")
        selected = [job for job in jobs["jobs"] if job["name"] == job_name]
        require(len(selected) == 1, f"Missing or ambiguous native job: {job_name}")
        job = selected[0]
        require(job["status"] == "completed" and job["conclusion"] == "success", job_name)
        require(runner in job["labels"], "Unexpected native runner labels")
        assets = gh_json(endpoint + "/artifacts?per_page=100")
        require(assets["total_count"] <= 100, "Unexpected artifact count")
        selected = [asset for asset in assets["artifacts"] if asset["name"] == artifact]
        require(len(selected) == 1 and not selected[0]["expired"], "Missing/expired artifact")
        asset = selected[0]
        require(asset["workflow_run"]["id"] == run_id, "Artifact belongs to another run")
        require(asset["workflow_run"]["head_sha"] == run["head_sha"], "Artifact SHA mismatch")
        result[kind] = {
            "run_id": run_id,
            "head_sha": run["head_sha"],
            "workflow": workflow,
            "job_id": job["id"],
            "job_name": job_name,
            "job_conclusion": "success",
            "artifact_id": asset["id"],
            "artifact_name": artifact,
            "run_status": run["status"],
            "run_conclusion": run["conclusion"],
        }
    write_json(args.output, result)
    print(json.dumps(result, indent=2))


def safe_members(archive, root, *, windows=False):
    """Validate confinement before ditto can materialize .app symlinks."""
    seen = set()
    for entry in archive.infolist():
        path = PurePosixPath(entry.filename)
        require(
            not path.is_absolute()
            and ".." not in path.parts
            and path.parts
            and path.parts[0] == root
            and "\\" not in entry.filename
            and ":" not in entry.filename
            and path.as_posix() == entry.filename.rstrip("/"),
            f"Unsafe ZIP member: {entry.filename}",
        )
        key = entry.filename.rstrip("/")
        if windows:
            reserved = {"CON", "PRN", "AUX", "NUL"} | {
                f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
            }
            require(
                all(
                    part == part.rstrip(" .")
                    and part.split(".")[0].upper() not in reserved
                    and not any(ord(c) < 32 or c in '<>"|?*' for c in part)
                    for part in path.parts
                ),
                f"Unsafe Windows ZIP member: {entry.filename}",
            )
            key = key.casefold()
        require(key not in seen, f"Duplicate ZIP member: {key}")
        seen.add(key)
        if stat.S_ISLNK(entry.external_attr >> 16):
            require(not windows, f"Windows ZIP links are not allowed: {entry.filename}")
            target = archive.read(entry).decode("utf-8")
            resolved = posixpath.normpath(posixpath.join(str(path.parent), target))
            require(
                not target.startswith("/")
                and "\\" not in target
                and resolved.startswith(root + "/"),
                f"Escaping ZIP link: {entry.filename}",
            )


def extract_verified(archive, destination, root, *, windows=False):
    fields = archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()
    require(len(fields) == 2 and fields[1].lstrip("*") == archive.name, "Bad ZIP checksum name")
    require(digest(archive) == fields[0], "ZIP checksum mismatch")
    with zipfile.ZipFile(archive) as zipped:
        safe_members(zipped, root, windows=windows)
    require(not destination.exists(), "Extraction destination must be new")
    if windows:
        # Paths, case aliases and every link have been rejected before writing.
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(destination)
    else:
        subprocess.run(["ditto", "-x", "-k", str(archive), str(destination)], check=True)
    return destination / root


def source_dependencies(work):
    archive = work / PUBLIC_ARCHIVE
    with urlopen(PUBLIC_URL, timeout=60) as response, archive.open("xb") as stream:
        shutil.copyfileobj(response, stream)
    require(digest(archive) == PUBLIC_SHA256, "Pinned public dependency ZIP changed")
    destination = work / "authorized-dependencies"
    with zipfile.ZipFile(archive) as zipped:
        safe_members(zipped, "GAMForge")
        manifest = json.loads(zipped.read("GAMForge/FULL-BUNDLE.json"))
        require(manifest["sdk_firmware_redistribution_authorized"] is True, "Missing authorization")
        require(manifest["games_included"] is False, "Unexpected source package")
        for name, expected in manifest["dependencies"].items():
            path = PurePosixPath(name)
            allowed = name in ("roms/8.BIN", "roms/E.BIN") or (
                path.parts[0] in ("sdk9288", "sdk9288t", "sdk9288s")
                and (path.suffix.lower() == ".h" or path.name == "readme.txt")
            )
            if not allowed:
                continue  # Never extract Windows tools, Python or CRT binaries.
            require(".." not in path.parts and not path.is_absolute(), "Unsafe dependency path")
            data = zipped.read("GAMForge/dependencies/" + name)
            require(
                hashlib.sha256(data).hexdigest() == expected, f"Dependency hash mismatch: {name}"
            )
            output = destination.joinpath(*path.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
    return destination


def synthetic_game():
    """Original 14-byte 6502 program plus deterministic, non-game resource data."""
    game = bytearray(0x5000)
    game[:4] = b"GAM\0"
    game[6:14] = b"MACSMOKE"
    struct.pack_into("<HI", game, 0x40, 0x5046, 0x4000)
    game[0x46:0x4A] = bytes.fromhex("20 60 50 60")  # JSR $5060; RTS
    game[0x60:0x6A] = bytes.fromhex("A9 01 85 80 A2 03 CA D0 FD 60")
    game[0x4000:] = bytes((i * 71 + (i >> 3) * 29) & 255 for i in range(0x1000))
    require(hashlib.sha256(game).hexdigest() == FIXTURE_SHA256, "Fixture unexpectedly changed")
    return bytes(game)


def isolated_environment(work):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(("A9288", "ATSW600", "PYTHON", "CONDA", "DYLD_"))
        and k.upper()
        not in {
            "CC",
            "CXX",
            "CPATH",
            "C_INCLUDE_PATH",
            "CPLUS_INCLUDE_PATH",
            "INCLUDE",
            "LIB",
            "LIBPATH",
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "LD_LIBRARY_PATH",
        }
    }
    env.update(
        A9288_USER_DATA=str(work / "profile"),
        A9288_WORKSPACE=str(work / "work"),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
    )
    if os.name == "nt":
        system = next(v for k, v in env.items() if k.upper() == "SYSTEMROOT")
        env.update(LOCALAPPDATA=str(work / "profile"), PATH=str(Path(system) / "System32"))
    else:
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    return env


def verify_bundle(bundle, work):
    require(not work.exists(), "Verification directory must be new")
    work.mkdir(parents=True)
    macos = sys.platform == "darwin"
    relative_cli = "GAMForge.app/Contents/MacOS/GAMForge" if macos else "GAMForge-CLI.exe"
    relative_deps = "GAMForge.app/Contents/Resources/dependencies" if macos else "dependencies"
    require((bundle / relative_cli).is_file(), "Expected native full bundle CLI")
    metadata = json.loads((bundle / "FULL-BUNDLE.json").read_text(encoding="utf-8"))
    require(set(metadata["targets"]) == {"9288", "9288t", "9288s", "tsw600"}, "Missing targets")
    game = work / "合成 输入" / "转换 测试.gam"
    game.parent.mkdir()
    game.write_bytes(synthetic_game())
    env = isolated_environment(work)
    evidence = {
        "host": platform.platform(),
        "architecture": platform.machine(),
        "fixture_sha256": FIXTURE_SHA256,
        "fixture_bytes": game.stat().st_size,
        "actual_game_tested": False,
        "cases": [],
    }
    original = bundle
    for index, (target, external) in enumerate(
        [("9288", False), ("9288t", False), ("9288s", False), ("tsw600", False), ("9288t", True)]
    ):
        if index == 4:
            # Re-test dependency discovery after moving to a different Unicode path.
            bundle = work / "移动 后的应用" / "GAMForge"
            shutil.copytree(original, bundle, symlinks=macos)
        cli = bundle / relative_cli
        deps = (bundle / relative_deps).resolve()
        probe = json.loads(
            subprocess.check_output([str(cli), "--self-test"], env=env, encoding="utf-8")
        )
        require(probe["self_test"] == "PASS" and probe["boot_helper"], "Frozen self-test failed")
        for path in probe["dependencies"].values():
            require(Path(path).resolve().is_relative_to(deps), "Leaked developer dependency path")
        if macos:
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(bundle / "GAMForge.app")],
                check=True,
            )
        output = work / f"输出 {index}" / "验证.exe"
        output.parent.mkdir()
        command = [
            str(cli),
            "convert",
            str(game),
            "--target",
            target,
            "--app-name",
            "验证",
            "--output",
            str(output),
        ]
        if external:
            command.append("--external-resources")
        with (output.parent / "conversion.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                command,
                cwd=work,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=600,
            )
        report = json.loads(output.with_suffix(".report.json").read_text(encoding="utf-8"))
        require(
            report["target"] == target and report["external_resources"] is external,
            "Wrong conversion mode",
        )
        require(report["standalone_link_complete"] is True, "Unresolved native link")
        require(report["runtime_interpreter_fallback"] is False, "Unexpected interpreter fallback")
        require(report["output_exe_sha256"] == digest(output), "EXE digest mismatch")
        require(0 < output.stat().st_size < 1024 * 1024, "Invalid game EXE size")
        require(
            Path(report["sdk"]).resolve().is_relative_to(deps),
            "External SDK leaked into conversion",
        )
        expected_scale = "1.5x-sharp" if target == "9288t" else "2x" if target == "9288" else "1x"
        require(report["display_scale"] == expected_scale, "Wrong default display scale")
        magic = b"D300" if target in ("9288s", "tsw600") else b"KF2\0"
        require(output.read_bytes()[:4] == magic, "Wrong device executable format")
        snapshot = Path(report["compressed_boot_snapshot_object"]).with_suffix(".bin")
        boot = snapshot.read_bytes()
        require(boot[:8] == b"C65BOOT\0" and len(boot) >= 64, "Invalid boot snapshot header")
        boot_version, ram_size, pc, _regs, _flags, banks = struct.unpack_from("<6I", boot, 8)
        require(boot_version == 2 and len(boot) == 64 + ram_size, "Invalid snapshot layout")
        require(pc == 0x5046 and banks == 16, "Wrong synthetic boot entry/banks")
        resource_sha256 = None
        if external:
            resource = output.parent / report["resource_file"]
            require(digest(resource) == report["resource_sha256"], "RES digest mismatch")
            require(report["resource_install_directory"] == "A:\\系统\\数据\\", "Wrong RES path")
            resource_sha256 = digest(resource)
        evidence["cases"].append(
            {
                "target": target,
                "external_resources": external,
                "relocated_bundle": index == 4,
                "display_scale": report["display_scale"],
                "exe_bytes": output.stat().st_size,
                "exe_sha256": digest(output),
                "resource_sha256": resource_sha256,
                "boot_snapshot_bytes": len(boot),
                "boot_snapshot_sha256": digest(snapshot),
                "boot_header_sha256": hashlib.sha256(boot[:64]).hexdigest(),
                "boot_ram_sha256": hashlib.sha256(boot[64:]).hexdigest(),
                "result": "PASS",
            }
        )
        print(f"PASS: {target} external={external} relocated={index == 4}", flush=True)
    evidence["result"] = "PASS"
    write_json(work / "validation.json", evidence)
    return evidence


def assemble(args):
    from build_toolchain import LEGACY_BUILDER_SHA256, file_sha256, reusable_output

    require(
        sys.platform == "darwin" and platform.machine() == args.architecture,
        "Need matching native Mac",
    )
    require(not args.work_dir.exists(), "Assembly work directory must be new")
    args.work_dir.mkdir(parents=True)
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(
        provenance["source_sha"] == head and provenance["app"]["head_sha"] == head,
        "Source changed after provenance check",
    )
    app_zip = args.app_artifacts / f"gamforge-{version}-macos-{args.architecture}.zip"
    tools_name = f"s1c33-9288-toolchain-macos-{args.architecture}"
    tools_zip = args.toolchain_artifacts / (tools_name + ".zip")
    app = extract_verified(app_zip, args.work_dir / "light", "GAMForge")
    toolchain = extract_verified(tools_zip, args.work_dir / "tools", tools_name)
    manifest = json.loads((ROOT / "toolchain/manifest.json").read_text())
    expected = {
        **manifest,
        "host": f"macos-{args.architecture}",
        "deployment_target": "11.0",
        "patch_sha256": file_sha256(ROOT / "toolchain" / manifest["patch"]),
        "builder_sha256": file_sha256(ROOT / "scripts/build_toolchain.py"),
    }
    # The first native CI build omitted Clang's standard resource headers. Reuse
    # its verified binaries only through the builder's explicit, hash-pinned
    # migration; never waive normal provenance/hash validation to save a build.
    input_manifest = json.loads((toolchain / "manifest.json").read_text(encoding="utf-8"))
    if input_manifest.get("builder_sha256") == LEGACY_BUILDER_SHA256:
        source = args.work_dir / "pinned-resource-source"
        for command in (
            ["git", "init", str(source)],
            ["git", "-C", str(source), "remote", "add", "origin", manifest["repository"]],
            [
                "git",
                "-C",
                str(source),
                "fetch",
                "--depth=1",
                "--filter=blob:none",
                "origin",
                manifest["revision"],
            ],
            ["git", "-C", str(source), "sparse-checkout", "init", "--cone"],
            ["git", "-C", str(source), "sparse-checkout", "set", "clang/lib/Headers"],
            ["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"],
        ):
            subprocess.run(command, check=True)
        repaired = args.work_dir / "repaired-tools"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/build_toolchain.py"),
                "--expect-host",
                expected["host"],
                "--import-tools",
                str(toolchain),
                "--resource-headers",
                str(source / "clang/lib/Headers"),
                "--output-dir",
                str(repaired),
            ],
            check=True,
        )
        toolchain = repaired / tools_name
    require(
        reusable_output(toolchain, expected),
        "Toolchain manifest/builder/patch/file hashes differ from source",
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_toolchain.py"),
            "--expect-host",
            expected["host"],
            "--verify-only",
            str(toolchain),
        ],
        check=True,
    )
    deps = source_dependencies(args.work_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    archive = args.output_dir / f"gamforge-{version}-full-macos-{args.architecture}.zip"
    require(not archive.exists(), "Refusing to overwrite an existing full ZIP")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_full_bundle.py"),
            "--platform",
            "macos",
            "--architecture",
            args.architecture,
            "--portable-dir",
            str(app),
            "--sdk",
            str(deps / "sdk9288"),
            "--sdk9288t",
            str(deps / "sdk9288t"),
            "--sdk9288s",
            str(deps / "sdk9288s"),
            "--toolchain",
            str(toolchain),
            "--rom8",
            str(deps / "roms/8.BIN"),
            "--rome",
            str(deps / "roms/E.BIN"),
            "--authorized-redistribution",
            "--output",
            str(archive),
        ],
        check=True,
    )
    full = extract_verified(archive, args.work_dir / "full", "GAMForge")
    evidence = verify_bundle(full, args.work_dir / "isolated-conversion")
    evidence.update(
        provenance=provenance,
        public_dependencies_sha256=PUBLIC_SHA256,
        source_sha=head,
        archive_sha256=digest(archive),
        toolchain_input_manifest=input_manifest,
        toolchain_manifest=json.loads((toolchain / "manifest.json").read_text(encoding="utf-8")),
        release_published=False,
    )
    write_json(args.output_dir / f"validation-macos-{args.architecture}.json", evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    runs = commands.add_parser("check-runs")
    runs.add_argument("--app-run", type=int, required=True)
    runs.add_argument("--toolchain-run", type=int, required=True)
    runs.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    runs.add_argument("--branch", required=True)
    runs.add_argument("--sha", required=True)
    runs.add_argument("--output", type=Path, required=True)
    bundle = commands.add_parser("assemble")
    bundle.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    for name in ("app-artifacts", "toolchain-artifacts", "provenance", "work-dir", "output-dir"):
        bundle.add_argument("--" + name, type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    if args.command == "check-runs":
        check_runs(args)
    elif args.command == "assemble":
        assemble(args)
    else:
        verify_bundle(args.bundle, args.work_dir)


if __name__ == "__main__":
    main()
