"""Seed an expired native cache from a SHA-pinned, published toolchain artifact.

No imported executable is run here. The normal --reuse builder still verifies
native execution, ABI and headers before republishing its same-run artifact.
"""

import argparse
import re
import shutil
import tempfile
from pathlib import Path

from build_release_full import HOSTS, expected_toolchain
from build_toolchain import file_sha256, reusable_output
from verify_full_bundle import extract_verified, require


def restore(artifacts, output_dir, host, sha256):
    require(host in HOSTS, "Unsupported toolchain host")
    require(re.fullmatch(r"[0-9a-f]{64}", sha256), "Expected pinned archive SHA-256")
    name = "s1c33-9288-toolchain-" + host
    archive = artifacts / (name + ".zip")
    destination = output_dir / name
    if not archive.is_file() or destination.exists():
        print("Bootstrap unavailable or cache already present; use normal builder")
        return False
    require(file_sha256(archive) == sha256, "Pinned bootstrap archive checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="gamforge-toolchain-bootstrap-") as temporary:
        root = extract_verified(
            archive, Path(temporary) / "verified", name, windows=host == "windows-x64"
        )
        # A source/ABI/patch/builder/header change invalidates this seed. Leave
        # output absent so the ordinary source build can proceed cleanly.
        if not reusable_output(root, expected_toolchain(host)):
            print("Pinned tools differ from current source; rebuilding from source")
            return False
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root, destination)
    print(f"Restored verified bootstrap: {host} SHA256={sha256}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--host", choices=HOSTS, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    restore(args.artifacts, args.output_dir, args.host, args.sha256)


if __name__ == "__main__":
    main()
