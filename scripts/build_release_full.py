"""Build verified Full release packages from this workflow run's native artifacts.

This does not select cross-run artifacts or publish a release. The workflow
downloads the app and toolchain artifacts from its own run. Dependencies come
only from the SHA-pinned, authorized public bundle; its host binaries are never
used. Final assets appear in output-dir only after isolated conversion tests.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from build_toolchain import file_sha256, host_tag, reusable_output
from verify_full_bundle import (
    PUBLIC_SHA256,
    PUBLIC_URL,
    REPOSITORY,
    digest,
    extract_verified,
    require,
    source_dependencies,
    verify_bundle,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
HOSTS = ("windows-x64", "macos-arm64", "macos-x86_64")
CRT_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def source_provenance():
    """Bind same-run assembly to the checked-out commit, not a caller's label."""
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None, "Invalid source commit")
    expected = os.environ.get("GITHUB_SHA")
    require(not expected or expected == head, "Source differs from GITHUB_SHA")
    fields = {
        "repository": "GITHUB_REPOSITORY",
        "run_id": "GITHUB_RUN_ID",
        "run_attempt": "GITHUB_RUN_ATTEMPT",
        "workflow": "GITHUB_WORKFLOW",
        "workflow_ref": "GITHUB_WORKFLOW_REF",
        "ref": "GITHUB_REF",
        "event": "GITHUB_EVENT_NAME",
    }
    github = {key: os.environ.get(name) for key, name in fields.items()}
    if os.environ.get("GITHUB_ACTIONS") == "true":
        require(expected == head, "GitHub Actions requires an exact source SHA")
        require(github["repository"] == REPOSITORY, "Only official repository builds are accepted")
        require(github["event"] in ("push", "workflow_dispatch"), "Untrusted release event")
        require(all(github[key] for key in fields), "Incomplete GitHub same-run provenance")
        require(
            github["run_id"].isdigit() and github["run_attempt"].isdigit(),
            "Invalid GitHub run identity",
        )
    return {"source_sha": head, "artifact_scope": "same-workflow-run", "github": github}


def validate_host(args):
    require(args.host == host_tag(), "Full assembly requires the matching native host")
    if args.host == "windows-x64":
        require(args.vc_runtime is not None, "Windows requires --vc-runtime")
        # Accept only the explicit x64 VS redistributable subtree. System32,
        # Debug_NonRedist and x86 CRTs are not redistributable native inputs.
        require(
            re.search(
                r"(?:^|/)VC/Redist/MSVC/\d+(?:\.\d+){1,3}/x64/Microsoft\.VC\d+\.CRT$",
                args.vc_runtime.as_posix(),
                re.IGNORECASE,
            )
            is not None,
            "Use the exact VS VC/Redist/MSVC/<version>/x64/Microsoft.VC*.CRT directory",
        )
        require(args.vc_runtime.is_dir(), "Missing VC redistributable directory")
        paths = (args.vc_runtime, *args.vc_runtime.parents, *args.vc_runtime.glob("*.dll"))
        require(
            not any(
                path.is_symlink() or getattr(path, "is_junction", lambda: False)() for path in paths
            ),
            "VC runtime links are not accepted",
        )
        for name in CRT_DLLS:
            require((args.vc_runtime / name).is_file(), f"Redistributable CRT missing {name}")
    else:
        require(args.vc_runtime is None, "macOS must not include Windows VC runtime")


def expected_toolchain(host):
    manifest = json.loads((ROOT / "toolchain/manifest.json").read_text(encoding="utf-8"))
    return {
        **manifest,
        "host": host,
        "deployment_target": None if host == "windows-x64" else "11.0",
        "patch_sha256": file_sha256(ROOT / "toolchain" / manifest["patch"]),
        "builder_sha256": file_sha256(ROOT / "scripts/build_toolchain.py"),
    }


def validate_dependencies(deps):
    for name in (
        "sdk9288/Down_Include/Dsys.h",
        "sdk9288t/include/Dsys.h",
        "sdk9288s/Down_Include/Dsys.h",
    ):
        require((deps / name).is_file(), f"Missing authorized SDK dependency: {name}")
    for name in ("8.BIN", "E.BIN"):
        path = deps / "roms" / name
        require(path.is_file() and path.stat().st_size == 2 * 1024 * 1024, f"Missing ROM: {name}")


def assemble(args):
    require(args.authorized_redistribution, "Explicit redistribution authorization is required")
    validate_host(args)
    provenance = source_provenance()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    name = f"gamforge-{version}-full-{args.host}.zip"
    outputs = (name, name + ".sha256", f"validation-{args.host}.json")
    require(
        not any((args.output_dir / output).exists() for output in outputs),
        "Refusing to overwrite existing Full release assets",
    )
    require(not args.work_dir.exists(), "Assembly work directory must be new")
    args.work_dir.mkdir(parents=True)
    windows = args.host == "windows-x64"
    app_zip = args.app_artifacts / f"gamforge-{version}-{args.host}.zip"
    tools_name = f"s1c33-9288-toolchain-{args.host}"
    tools_zip = args.toolchain_artifacts / (tools_name + ".zip")
    app = extract_verified(app_zip, args.work_dir / "light", "GAMForge", windows=windows)
    toolchain = extract_verified(tools_zip, args.work_dir / "tools", tools_name, windows=windows)
    # No imported compiler executable is run until current source, builder,
    # patch, complete resource-header set and every payload hash agree.
    require(
        reusable_output(toolchain, expected_toolchain(args.host)),
        "Toolchain manifest/builder/patch/file hashes differ from source",
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_toolchain.py"),
            "--expect-host",
            args.host,
            "--verify-only",
            str(toolchain),
        ],
        check=True,
    )
    deps = source_dependencies(args.work_dir)
    validate_dependencies(deps)
    pending = args.work_dir / "unpublished"
    pending.mkdir()
    archive = pending / name
    command = [
        sys.executable,
        str(ROOT / "scripts/build_full_bundle.py"),
        "--platform",
        "windows" if windows else "macos",
        "--architecture",
        "x86_64" if windows else args.host.removeprefix("macos-"),
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
    ]
    if windows:
        command.extend(("--vc-runtime", str(args.vc_runtime)))
    subprocess.run(command, check=True)
    full = extract_verified(archive, args.work_dir / "full", "GAMForge", windows=windows)
    evidence = verify_bundle(full, args.work_dir / "isolated-conversion")
    require(evidence.get("result") == "PASS", "Isolated Full verification did not pass")
    require(
        len(evidence.get("cases", [])) == 5
        and all(case.get("result") == "PASS" for case in evidence["cases"]),
        "All five isolated conversion cases must pass",
    )
    evidence.update(
        version=version,
        bundle_host=args.host,
        source_sha=provenance["source_sha"],
        provenance=provenance,
        public_dependencies_url=PUBLIC_URL,
        public_dependencies_sha256=PUBLIC_SHA256,
        archive_sha256=digest(archive),
        app_archive_sha256=digest(app_zip),
        toolchain_archive_sha256=digest(tools_zip),
        toolchain_manifest=json.loads((toolchain / "manifest.json").read_text(encoding="utf-8")),
        release_published=False,
    )
    if windows:
        evidence["vc_runtime_sha256"] = {
            path.name: digest(path) for path in sorted(args.vc_runtime.glob("*.dll"))
        }
    write_json(pending / outputs[2], evidence)
    # Nothing reaches the workflow's upload location before verification. Keep
    # unpublished failure artifacts in work-dir for diagnosis, never Release.
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for output in outputs:
        shutil.copyfile(pending / output, args.output_dir / output)
    print(f"Verified Full package: {args.output_dir / name}")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=HOSTS, required=True)
    for name in ("app-artifacts", "toolchain-artifacts", "work-dir", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--vc-runtime", type=Path)
    parser.add_argument("--authorized-redistribution", action="store_true")
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            # Preserve CRT link identity until validate_host has rejected it.
            setattr(args, name, value.absolute() if name == "vc_runtime" else value.resolve())
    try:
        assemble(args)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Full package validation failed: {error}\n")


if __name__ == "__main__":
    main()
