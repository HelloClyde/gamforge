"""Fail closed unless all three Full archives have matching conversion evidence."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

HOSTS = ("windows-x64", "macos-arm64", "macos-x86_64")
TARGETS = {"9288", "9288t", "9288s", "tsw600"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_assets(directory, tag, source_sha):
    require(re.fullmatch(r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", tag), "Invalid release tag")
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha), "Invalid source SHA")
    version = tag[1:]
    expected = set()
    for host in HOSTS:
        name = f"gamforge-{version}-full-{host}.zip"
        expected.update((name, name + ".sha256", f"validation-{host}.json"))
    actual = {p.name for p in directory.iterdir()}
    require(actual == expected, f"Full-only asset set mismatch: {sorted(actual ^ expected)}")
    require(all(p.is_file() and not p.is_symlink() for p in directory.iterdir()), "Invalid asset")
    for host in HOSTS:
        archive = directory / f"gamforge-{version}-full-{host}.zip"
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        fields = archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()
        require(fields == [digest, archive.name], f"Checksum mismatch: {host}")
        evidence = json.loads((directory / f"validation-{host}.json").read_text(encoding="utf-8"))
        require(evidence.get("result") == "PASS", f"Conversion validation failed: {host}")
        require(evidence.get("bundle_host") == host, f"Wrong native host: {host}")
        require(evidence.get("version") == version, f"Wrong validation version: {host}")
        require(evidence.get("source_sha") == source_sha, f"Wrong validation source: {host}")
        require(evidence.get("archive_sha256") == digest, f"Wrong validated archive: {host}")
        cases = evidence.get("cases", [])
        require(len(cases) == 5, f"Missing conversion tests: {host}")
        required_cases = {(target, False) for target in TARGETS} | {("9288t", True)}
        require(
            {(c.get("target"), c.get("external_resources")) for c in cases} == required_cases
            and all(c.get("result") == "PASS" for c in cases),
            f"Incomplete conversion coverage: {host}",
        )
        require(
            any(c.get("relocated_bundle") is True and c.get("external_resources") for c in cases),
            f"Missing relocated bundle test: {host}",
        )
        with zipfile.ZipFile(archive) as zipped:
            metadata = json.loads(zipped.read("GAMForge/FULL-BUNDLE.json"))
            require(
                metadata.get("edition") == "full" and metadata.get("version") == version,
                f"Not a Full bundle of this version: {host}",
            )
            require(set(metadata.get("targets", [])) == TARGETS, f"Missing target SDK: {host}")
            require(metadata.get("games_included") is False, f"Unexpected bundled games: {host}")
            require(
                metadata.get("sdk_firmware_redistribution_authorized") is True,
                f"Missing redistribution authorization: {host}",
            )
    return sorted(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("tag")
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    for name in check_assets(args.directory, args.tag, args.source_sha):
        print("PASS:", name)


if __name__ == "__main__":
    main()
