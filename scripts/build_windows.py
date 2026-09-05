"""Create a tested portable Windows ZIP; never collect user SDK/ROM/game files."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from a9288 import __version__
from a9288.compiler.boot import build_helper, bundled_helper

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.name != "nt":
        raise SystemExit("Build the Windows distribution on Windows.")
    build_helper(bundled_helper())
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build/pyinstaller"),
            str(ROOT / "packaging/windows.spec"),
        ],
        cwd=ROOT,
        check=True,
    )
    folder = ROOT / "dist/A9288-Translator"
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"):
        shutil.copyfile(ROOT / name, folder / name)
    shutil.copytree(ROOT / "docs", folder / "docs", dirs_exist_ok=True)
    # Self-test crosses a frozen worker boundary as well as inspecting data.
    executable = folder / "A9288-CLI.exe"
    result = subprocess.check_output([str(executable), "--self-test"], cwd=folder, encoding="utf-8")
    report = json.loads(result.strip())
    if report.get("self_test") != "PASS" or not report.get("boot_helper"):
        raise SystemExit("The frozen package failed its resource/boot-helper self-test")
    subprocess.run(
        [str(executable), "--worker", "compiler.backend", "--help"], cwd=folder, check=True
    )
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    for path in files:
        if path.suffix.lower() in (
            ".gam",
            ".sav",
            ".rom",
            ".map",
            ".raw",
            ".flat",
        ) or path.name.upper() in ("8.BIN", "E.BIN"):
            raise SystemExit(f"Private game/firmware artifact in distribution: {path}")
    manifest = {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    (folder / "MANIFEST.sha256.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    archive = ROOT / "dist" / f"a9288-translator-{__version__}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zipped.write(path, Path(folder.name) / path.relative_to(folder))
    checksum = archive.with_suffix(".zip.sha256")
    checksum.write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n",
        encoding="ascii",
    )
    print(f"Built {archive} ({archive.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
